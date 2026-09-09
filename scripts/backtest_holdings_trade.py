# -*- coding: utf-8 -*-
"""持仓个股「底买顶卖」双方案回测 —— 只读独立脚本，不修改任何 pipeline 代码。

标的：仅用户持仓中的 A 股个股（holdings_list.py 里 type=="stock"，共 10 只；ETF 全部排除）。

两个被比较的信号引擎（均无未来函数）：
  方案 A「后向窗口」：分型 = 3K 形态 + 前 4 根极值确认（顶：high 是 [i-4..i] 最高；
                       底：low 是 [i-4..i] 最低），右K收盘即确认，不做任何等待。
  方案 B「在线滚动」：3K 分型先作候选（连续同向取更强者），
                       出现反向 3K 分型时把前一分型「钉死」→ 才是有效信号。

共同交易规则（用户指定）：
  - 出现确认的底分型 → 次日开盘价全仓买入；出现确认的顶分型 → 次日开盘价清仓卖出；
  - 初始空仓、只做多、全仓切换；
  - A股 T+1：信号在右K收盘才确认（收盘后才能下单），成交价 = 下一交易日开盘价（方案代码里
    = 确认K的下一根合并K线开盘，即实际 T+1 可成交的最早价），无前视；
  - 费用：买入佣金万 2.5；卖出佣金万 2.5 + 印花税 0.05%；成交不另加滑点。

注：A/B/B3 事件引擎自本次起**默认 only_strong=True**（仅强势分型触发），与 AI 研判口径
    （review.py 规定 weak 分型不得评高）统一；脚本同时输出『全部分型』基线（only_strong=False）
    作对照，以及标准双向极值版作印证。

用法：python scripts/backtest_holdings_trade.py
输出：output/backtest/holdings_trade_<日期>/summary.json + trades_A.csv + trades_B.csv
      + trades_B3_gap3.csv（方案B3 = B + 顶底中K间隔≥3 成笔约束；本轮不生成 HTML）
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.environ.get("STOCKDB_SDK_PATH", r"D:\stockdb\pybao"))

from stock_sdk import init as sdk_init, rd as sdk_rd  # noqa: E402
from src.core.chanlun_processor import ChanlunProcessor  # noqa: E402

HOLDINGS_PY = r"C:\Users\lilon\.workbuddy\skills\图形识别选股\scripts\holdings_list.py"

FETCH_START = "20200101"   # 多取供合并K线/预热
SIGNAL_START = 20210104    # 净值起点：首个 >= 此日的合并K线
END = "20260909"
NEED_BARS = 200
BUY_FEE = 0.00025          # 佣金万2.5
SELL_FEE = 0.00025 + 0.0005  # 佣金万2.5 + 印花税0.05%
BK = 4                     # 后向窗口根数
MIN_GAP = 3                # 方案B3：成笔最小约束，顶底中K间隔 >= 3 根合并K线


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def load_stock_holdings() -> list:
    """只取 type=='stock' 的持仓（ETF 排除）。"""
    ns: dict = {}
    with open(HOLDINGS_PY, encoding="utf-8") as f:
        exec(compile(f.read(), HOLDINGS_PY, "exec"), ns)
    return [(c, n) for c, n, ty in ns["HOLDINGS"] if ty == "stock"]


def to_int8(x) -> int:
    s = "".join(ch for ch in str(x) if ch.isdigit())
    return int(s[:8]) if s else 0


def rows_to_df(rows: list) -> pd.DataFrame | None:
    if not rows or len(rows) < NEED_BARS:
        return None
    df = pd.DataFrame(rows)
    df["datetime"] = df["date"]
    df = df.sort_values("datetime").reset_index(drop=True)
    keep = df[["datetime", "open", "high", "low", "close", "is_st", "name"]].copy()
    for col in ("open", "high", "low", "close"):
        keep[col] = pd.to_numeric(keep[col], errors="coerce")
    keep = keep.dropna(subset=["open", "high", "low", "close"])
    if len(keep) < NEED_BARS or keep["close"].le(0).any():
        return None
    return keep


def build_merged(df_raw: pd.DataFrame):
    """trim → merge → identify，返回合并K线（带分型标记）。"""
    proc = ChanlunProcessor()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        trimmed = proc.trim_data_by_extremes(df_raw)
        if trimmed.empty or len(trimmed) < 60:
            return None
        merged = proc.merge_klines(trimmed)
        if merged.empty or len(merged) < 60:
            return None
        tagged = proc.identify_fractals(merged)
    return tagged


def identify_standard_fractals(merged: pd.DataFrame) -> pd.DataFrame:
    """标准缠论顶底分型：双向极值判定。

    与 chanlun_processor.identify_fractals 的『半条件宽松版』的区别：
      - 顶分型不仅要求中间K high 最高，还要求 low 也是三K中最高（完全在最上方）；
      - 底分型不仅要求中间K low 最低，还要求 high 也是三K中最低（完全在最下方）。
    这就是教科书标准定义，会剔除一批『单向极值』的非标准分型。
    """
    if merged is None or len(merged) < 3:
        return merged
    res = merged.copy()
    res["is_fractal"] = False
    res["fractal_type"] = None
    klines = res.to_dict("records")
    n = len(klines)
    for i in range(1, n - 1):
        k1, k2, k3 = klines[i - 1], klines[i], klines[i + 1]
        is_top = (k2["high"] > k1["high"] and k2["high"] > k3["high"] and
                  k2["low"] >= k1["low"] and k2["low"] >= k3["low"])
        is_bottom = (k2["low"] < k1["low"] and k2["low"] < k3["low"] and
                     k2["high"] <= k1["high"] and k2["high"] <= k3["high"])
        if is_top:
            res.loc[i, "fractal_type"] = "top"
            res.loc[i, "is_fractal"] = True
        elif is_bottom:
            res.loc[i, "fractal_type"] = "bottom"
            res.loc[i, "is_fractal"] = True
    return res


def build_merged_both(df_raw: pd.DataFrame):
    """trim → merge 后，分别用『原半条件版』和『标准双向极值版』标记分型，返回 (tagged, tagged_std)。"""
    proc = ChanlunProcessor()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        trimmed = proc.trim_data_by_extremes(df_raw)
        if trimmed.empty or len(trimmed) < 60:
            return None, None
        merged = proc.merge_klines(trimmed)
        if merged.empty or len(merged) < 60:
            return None, None
        tagged = proc.identify_fractals(merged)
    tagged_std = identify_standard_fractals(merged)
    return tagged, tagged_std


def series_of(tagged: pd.DataFrame) -> dict:
    n = len(tagged)
    d8 = [to_int8(x) for x in tagged["datetime"].values]
    op = tagged["open"].astype(float).values
    hi = tagged["high"].astype(float).values
    lo = tagged["low"].astype(float).values
    cl = tagged["close"].astype(float).values
    isf = tagged["is_fractal"].values.astype(bool)
    ft = tagged["fractal_type"].values
    sraw = tagged["fractal_strength"].values if "fractal_strength" in tagged.columns else None
    ftype = [None if (not isf[i]) or ft[i] not in ("top", "bottom") else ft[i]
             for i in range(n)]
    # strength 与 ftype 行对齐：仅分型位置有值，其余 None
    strg = [None] * n
    if sraw is not None:
        for i in range(n):
            if ftype[i] is not None:
                v = sraw[i]
                strg[i] = None if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)
    return {"n": n, "d8": d8, "open": op, "high": hi, "low": lo,
            "close": cl, "ftype": ftype, "strength": strg}


def events_backward(s: dict, only_strong: bool = True) -> list:
    """方案A：3K形态 + 前BK根极值。返回 [(成交bar, type)]，成交bar = 右K的下 1 根。

    only_strong（默认 True）= 信号引擎默认仅做强势分型：弱分型（中继型）不构成
    有效反转，跳过。该开关使 A 方案信号与 AI 研判口径统一（review.py 规定 weak 不评高）。
    传 only_strong=False 则对全部分型触发（作对照基线）。
    """
    ev = []
    n, d8 = s["n"], s["d8"]
    strg = s.get("strength")
    for i in range(BK, n - 2):
        typ = s["ftype"][i]
        if typ is None:
            continue
        if only_strong and strg is not None and strg[i] == "weak":
            continue
        exe = i + 2                       # 右K=i+1 收盘确认，下一根开盘成交
        if exe >= n or d8[exe] < SIGNAL_START:
            continue
        if typ == "top" and s["high"][i] < max(s["high"][i - BK:i]):
            continue
        if typ == "bottom" and s["low"][i] > min(s["low"][i - BK:i]):
            continue
        ev.append((exe, typ))
    return ev


def events_rolling(s: dict, min_gap: int | None = None, only_strong: bool = True) -> list:
    """方案B：候选 + 反向钉死。返回 [(成交bar, 被钉死分型type)]。

    min_gap 非 None 时启用「最小成笔约束」：候选分型中K 与 反向分型中K
    的合并K线间距必须 >= min_gap 才允许钉死（成笔）；间距不足说明该
    候选只是盘整毛刺，不构成笔端点 → 丢弃候选，反向分型转为新候选，
    不产生交易事件。

    only_strong（默认 True）：被钉死的候选若为弱分型（中继型）则不产生交易，
    反向分型转为新候选；与 A 方案口径统一。
    """
    ev = []
    n, d8 = s["n"], s["d8"]
    strg = s.get("strength")
    pend_t, pend_i = None, -1
    for i in range(1, n - 1):
        typ = s["ftype"][i]
        if typ is None:
            continue
        # 该分型的右K = i+1，右K收盘时它才“可见”
        if d8[i + 1] < SIGNAL_START:
            continue
        if pend_t is None:
            pend_t, pend_i = typ, i
            continue
        if typ == pend_t:
            better = ((typ == "top" and s["high"][i] >= s["high"][pend_i]) or
                      (typ == "bottom" and s["low"][i] <= s["low"][pend_i]))
            if better:
                pend_t, pend_i = typ, i
            continue
        # 反向出现：先检查最小成笔间隔（顶底中K间距）
        if min_gap is not None and (i - pend_i) < min_gap:
            pend_t, pend_i = typ, i      # 间距不足：pend 是毛刺，丢弃并转候选
            continue
        # 仅做强势：被钉死候选为弱分型 → 不交易，反向分型转新候选
        if only_strong and strg is not None and strg[pend_i] == "weak":
            pend_t, pend_i = typ, i
            continue
        # 间距达标 → 把 pend 钉死；成交bar = 反向分型右K的下 1 根
        exe = i + 2
        if exe < n and d8[exe] >= SIGNAL_START:
            ev.append((exe, pend_t))
        pend_t, pend_i = typ, i
    return ev


def simulate(events: list, s: dict, code: str, name: str) -> dict:
    """全仓底买顶卖，T+1 次日开盘成交。返回明细与净值曲线。"""
    n, d8, op, cl = s["n"], s["d8"], s["open"], s["close"]
    s0 = next((i for i in range(n) if d8[i] >= SIGNAL_START), None)
    if s0 is None or s0 + 1 >= n:
        return None

    cash, shares, holding = 1.0, 0.0, False
    trades = []
    buy_bar = -1
    equity = np.ones(n)

    for exe, typ in sorted(events, key=lambda x: x[0]):
        if not (s0 < exe < n):
            continue
        px = float(op[exe])
        if px <= 0:
            continue
        if typ == "bottom" and not holding:
            shares = cash / (px * (1 + BUY_FEE))
            cash = 0.0
            holding = True
            buy_bar = exe
        elif typ == "top" and holding:
            proceeds = shares * px * (1 - SELL_FEE)
            cost = shares * float(op[buy_bar]) * (1 + BUY_FEE)
            cash = proceeds
            shares = 0.0
            holding = False
            trades.append({
                "code": code, "name": name,
                "buy_date": str(d8[buy_bar]), "sell_date": str(d8[exe]),
                "buy_px": round(float(op[buy_bar]), 3),
                "sell_px": round(px, 3),
                "ret_pct": round((proceeds / cost - 1) * 100, 2),
                "days": max(1, exe - buy_bar),
            })
            buy_bar = -1

    # 每日净值（期末持仓按收盘估值并预扣卖出费用）
    for t in range(n):
        if holding:
            equity[t] = cash + shares * float(cl[t]) * (1 - SELL_FEE)
        else:
            equity[t] = cash
    equity[:s0] = 1.0

    # 买入持有基准：s0 开盘买入持有至最后
    px0 = float(op[s0])
    if px0 > 0 and float(cl[-1]) > 0:
        bh_end = (1 / (px0 * (1 + BUY_FEE))) * float(cl[-1]) * (1 - SELL_FEE)
        bh_ret = bh_end - 1
    else:
        bh_ret = 0.0

    strat_ret = float(equity[-1]) - 1.0

    curve = equity[s0:]
    peak = np.maximum.accumulate(curve)
    mdd = float((curve / peak - 1).min()) * 100 if len(curve) else 0.0

    closed = [t for t in trades]
    wins = sum(1 for t in closed if t["ret_pct"] > 0)
    return {
        "code": code, "name": name,
        "trades": trades,
        "n_trades": len(closed),
        "win_rate": round(wins / len(closed) * 100, 1) if closed else None,
        "ret_pct": round(strat_ret * 100, 2),
        "bh_ret_pct": round(bh_ret * 100, 2),
        "excess_pct": round((strat_ret - bh_ret) * 100, 2),
        "max_dd_pct": round(mdd, 2),
        "end_holding": holding,
        "equity": equity,
        "s0": s0,
    }


def fmt_num(v, unit=""):
    return "—" if v is None else f"{v:+.2f}{unit}"


def build_report(out_dir: str, rows: list, detail: dict, elapsed: float) -> str:
    pd.set_option("display.width", 220)
    def pct(x):
        return "—" if x is None else f"{x:.1f}%"
    html_rows = ""
    for r in rows:
        html_rows += (
            f"<tr><td>{r['name']}</td><td>{r['code']}</td>"
            f"<td class='num'>{r['A_n']}</td><td class='num'>{pct(r['A_win'])}</td>"
            f"<td class='{'pos' if r['A_ret']>0 else 'neg'}'>{r['A_ret']:+.2f}%</td>"
            f"<td class='{'pos' if r['A_ex']>0 else ('neg' if r['A_ex']<0 else '')}'>{r['A_ex']:+.2f}%</td>"
            f"<td class='num'>{r['B_n']}</td><td class='num'>{pct(r['B_win'])}</td>"
            f"<td class='{'pos' if r['B_ret']>0 else 'neg'}'>{r['B_ret']:+.2f}%</td>"
            f"<td class='{'pos' if r['B_ex']>0 else ('neg' if r['B_ex']<0 else '')}'>{r['B_ex']:+.2f}%</td>"
            f"<td class='{'pos' if r['bh']>0 else 'neg'}'>{r['bh']:+.2f}%</td></tr>")
    d = detail
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>持仓个股 底买顶卖 双方案回测</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1180px;margin:24px auto;padding:0 16px;color:#1f2329;font-size:14px}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:26px;border-left:4px solid #185FA5;padding-left:8px}}
table{{border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{border:1px solid #d9dce1;padding:5px 10px;text-align:center}}
th{{background:#f0f3f7}} .pos{{color:#C0392B;font-weight:500}} .neg{{color:#1E8449}}
.num{{color:#444}}
.note{{background:#FAF3E3;border:1px solid #E5D6A8;padding:10px 14px;border-radius:6px;font-size:13px}}
.meta{{color:#667;font-size:13px}}
.kpi{{display:inline-block;background:#f0f3f7;border:1px solid #d9dce1;border-radius:8px;
padding:10px 16px;margin:4px 10px 4px 0;font-size:13px}}
.kpi b{{font-size:18px}}
</style></head><body>
<h1>持仓个股「底买顶卖」双方案回测（无未来函数）</h1>
<p class="meta">标的：用户持仓 A 股个股 10 只（ETF 已排除）｜ 净值区间：2021-01-04 ~ 数据末（前复权日线）｜ 信号：缠论合并K线 3K 分型｜ 成交：确认右K收盘的下一交易时段开盘价（满足 T+1）｜ 费用：买入万2.5、卖出万2.5+印花税0.05%｜ 生成：{datetime.now():%Y-%m-%d %H:%M}｜ 耗时 {elapsed:.0f}s</p>
<div class="note"><b>方案定义</b>：<br>
<b>A 后向窗口</b>：分型=3K形态+前{BK}根极值确认（顶=此前{BK}根内最高、底=最低），右K收盘即确认、不等未来 → 底买顶卖即时执行。<br>
<b>B 在线滚动</b>：3K分型先作候选（连续同向取更强），出现<b>反向</b>3K分型才把前一分型“钉死”为有效信号 → 底买顶卖，信号少而滞后数根。<br>
两方案均：初始空仓、只做多、全仓切换；期末仍持仓按收盘估值并预扣卖出费用。</div>
<h2>组合汇总（10 只等权平均）</h2>
<div class="kpi">方案A 平均收益<br><b class="{'pos' if d['A_avg']>0 else 'neg'}">{d['A_avg']:+.2f}%</b></div>
<div class="kpi">方案B 平均收益<br><b class="{'pos' if d['B_avg']>0 else 'neg'}">{d['B_avg']:+.2f}%</b></div>
<div class="kpi">买入持有 平均<br><b class="{'pos' if d['BH_avg']>0 else 'neg'}">{d['BH_avg']:+.2f}%</b></div>
<div class="kpi">A 跑赢 BH<br><b>{d['A_beat']}/10 只</b></div>
<div class="kpi">B 跑赢 BH<br><b>{d['B_beat']}/10 只</b></div>
<div class="kpi">B 相对 A<br><b>{d['B_vs_A']:+.2f}pp</b></div>
<h2>分标的明细</h2>
<table>
<tr><th>名称</th><th>代码</th><th>A交易</th><th>A胜率</th><th>A收益</th><th>A超额vs持有</th>
<th>B交易</th><th>B胜率</th><th>B收益</th><th>B超额vs持有</th><th>买入持有</th></tr>
{html_rows}
</table>
<p class="meta">A/B 超额 = 方案收益 − 该股同期买入持有收益；期末持仓已按最后收盘估值。方案收益含交易成本，为统计研究、非投资建议。</p>
</body></html>"""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def fetch_one(code: str):
    """逐只取数 + 重试（stockdb 批量取 10 只偶发丢标的）。"""
    for attempt in range(6):
        try:
            d = sdk_rd.get_data([code], start=FETCH_START, end=END,
                                frequency="1d", fq="qfq")
            if d and d.get(code):
                return d[code]
        except Exception as e:  # noqa: BLE001
            err = str(e)
        else:
            err = "空数据"
        time.sleep(1.2 * (attempt + 1))
    log(f"  {code} 取数失败(重试6次) {err}")
    return None


def main() -> None:
    holdings = load_stock_holdings()
    log(f"持仓个股 {len(holdings)} 只: {[n for _, n in holdings]}")
    sdk_init(host="127.0.0.1", port=7899)
    t0 = time.time()

    rows, all_tr = [], {
        "A": [], "B": [], "B3": [],
        "As": [], "Bs": [], "B3s": [],
        "SA": [], "SB": [], "SB3": [],
    }
    for code, name in holdings:
        rdf = rows_to_df(fetch_one(code))
        if rdf is None:
            log(f"跳过 {code} {name}: 数据不足")
            continue
        tagged, tagged_std = build_merged_both(rdf)
        if tagged is None or tagged_std is None:
            log(f"跳过 {code} {name}: 无法构建合并K线")
            continue
        s = series_of(tagged)          # 原半条件版（已带 fractal_strength）
        ss = series_of(tagged_std)     # 标准双向极值版（无 strength 列 → 不被强弱过滤影响）
        # 全部分型基线（对照）：显式 only_strong=False
        ra = simulate(events_backward(s, only_strong=False), s, code, name)
        rb = simulate(events_rolling(s, only_strong=False), s, code, name)
        rb3 = simulate(events_rolling(s, min_gap=MIN_GAP, only_strong=False), s, code, name)
        # 强势分型（信号引擎默认口径）：only_strong 取默认 True
        ras = simulate(events_backward(s), s, code, name)
        rbs = simulate(events_rolling(s), s, code, name)
        rb3s = simulate(events_rolling(s, min_gap=MIN_GAP), s, code, name)
        # 标准双向极值版（对照早年结论：与半条件版零差异）
        sa = simulate(events_backward(ss), ss, code, name)
        sb = simulate(events_rolling(ss), ss, code, name)
        sb3 = simulate(events_rolling(ss, min_gap=MIN_GAP), ss, code, name)
        if any(x is None for x in (ra, rb, rb3, ras, rbs, rb3s, sa, sb, sb3)):
            log(f"跳过 {code} {name}: 起点不足")
            continue
        all_tr["A"].extend(ra["trades"]); all_tr["B"].extend(rb["trades"]); all_tr["B3"].extend(rb3["trades"])
        all_tr["As"].extend(ras["trades"]); all_tr["Bs"].extend(rbs["trades"]); all_tr["B3s"].extend(rb3s["trades"])
        all_tr["SA"].extend(sa["trades"]); all_tr["SB"].extend(sb["trades"]); all_tr["SB3"].extend(sb3["trades"])
        rows.append({
            "name": name, "code": code, "bh": ra["bh_ret_pct"],
            "A_n": ra["n_trades"], "A_ret": ra["ret_pct"], "A_ex": ra["excess_pct"],
            "As_n": ras["n_trades"], "As_ret": ras["ret_pct"], "As_ex": ras["excess_pct"],
            "B_n": rb["n_trades"], "B_ret": rb["ret_pct"], "B_ex": rb["excess_pct"],
            "Bs_n": rbs["n_trades"], "Bs_ret": rbs["ret_pct"], "Bs_ex": rbs["excess_pct"],
            "B3_n": rb3["n_trades"], "B3_ret": rb3["ret_pct"], "B3_ex": rb3["excess_pct"],
            "B3s_n": rb3s["n_trades"], "B3s_ret": rb3s["ret_pct"], "B3s_ex": rb3s["excess_pct"],
            "SA_n": sa["n_trades"], "SA_ret": sa["ret_pct"], "SA_ex": sa["excess_pct"],
            "SB_n": sb["n_trades"], "SB_ret": sb["ret_pct"], "SB_ex": sb["excess_pct"],
            "SB3_n": sb3["n_trades"], "SB3_ret": sb3["ret_pct"], "SB3_ex": sb3["excess_pct"],
        })
        log(f"{name}: A全={ra['ret_pct']:+.1f}% A强={ras['ret_pct']:+.1f}%(#{ras['n_trades']}) | "
            f"B全={rb['ret_pct']:+.1f}% B强={rbs['ret_pct']:+.1f}% B3全={rb3['ret_pct']:+.1f}% B3强={rb3s['ret_pct']:+.1f}% | "
            f"标A={sa['ret_pct']:+.1f}% BH={ra['bh_ret_pct']:+.1f}%")

    if not rows:
        log("无任何有效标的")
        return
    df = pd.DataFrame(rows)

    def avg(k):
        return float(df[k].mean())

    detail = {
        "stocks": len(rows),
        "BH_avg": avg("bh"),
        "A_avg": avg("A_ret"), "B_avg": avg("B_ret"), "B3_avg": avg("B3_ret"),
        "As_avg": avg("As_ret"), "Bs_avg": avg("Bs_ret"), "B3s_avg": avg("B3s_ret"),
        "SA_avg": avg("SA_ret"), "SB_avg": avg("SB_ret"), "SB3_avg": avg("SB3_ret"),
        "A_beat": int((df["A_ex"] > 0).sum()), "B_beat": int((df["B_ex"] > 0).sum()),
        "B3_beat": int((df["B3_ex"] > 0).sum()),
        "As_beat": int((df["As_ex"] > 0).sum()), "Bs_beat": int((df["Bs_ex"] > 0).sum()),
        "B3s_beat": int((df["B3s_ex"] > 0).sum()),
        "SA_beat": int((df["SA_ex"] > 0).sum()), "SB_beat": int((df["SB_ex"] > 0).sum()),
        "SB3_beat": int((df["SB3_ex"] > 0).sum()),
        "As_vs_A": avg("As_ret") - avg("A_ret"),
        "Bs_vs_B": avg("Bs_ret") - avg("B_ret"),
        "B3s_vs_B3": avg("B3s_ret") - avg("B3_ret"),
        "SA_vs_A": avg("SA_ret") - avg("A_ret"),
        "SB_vs_B": avg("SB_ret") - avg("B_ret"),
        "SB3_vs_B3": avg("SB3_ret") - avg("B3_ret"),
    }
    out_dir = os.path.join(ROOT, "output", "backtest",
                           f"holdings_trade_{datetime.now():%Y%m%d}")
    os.makedirs(out_dir, exist_ok=True)
    csv_map = (("A", "trades_A.csv"), ("B", "trades_B.csv"),
               ("B3", f"trades_B3_gap{MIN_GAP}.csv"),
               ("As", "trades_A_strong.csv"), ("Bs", "trades_B_strong.csv"),
               ("B3s", f"trades_B3_gap{MIN_GAP}_strong.csv"),
               ("SA", "trades_StdA.csv"), ("SB", "trades_StdB.csv"),
               ("SB3", f"trades_StdB3_gap{MIN_GAP}.csv"))
    for k, fn in csv_map:
        pd.DataFrame(all_tr[k]).to_csv(os.path.join(out_dir, fn),
                                       index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2)

    print("\n=== 组合汇总（等权平均；原『半条件宽松版』 / 强势分型(默认) / 标准『双向极值版』）===")
    print(f"买入持有                {detail['BH_avg']:+.2f}%")
    print(f"原版 A/B/B3        {detail['A_avg']:+.2f}% / {detail['B_avg']:+.2f}% / {detail['B3_avg']:+.2f}%   "
          f"(跑赢BH {detail['A_beat']}/{detail['B_beat']}/{detail['B3_beat']})")
    print(f"强势 A/B/B3(默认)  {detail['As_avg']:+.2f}% / {detail['Bs_avg']:+.2f}% / {detail['B3s_avg']:+.2f}%   "
          f"(跑赢BH {detail['As_beat']}/{detail['Bs_beat']}/{detail['B3s_beat']})  "
          f"Δ全量 {detail['As_vs_A']:+.2f}/{detail['Bs_vs_B']:+.2f}/{detail['B3s_vs_B3']:+.2f}pp")
    print(f"标准 A/B/B3        {detail['SA_avg']:+.2f}% / {detail['SB_avg']:+.2f}% / {detail['SB3_avg']:+.2f}%   "
          f"(跑赢BH {detail['SA_beat']}/{detail['SB_beat']}/{detail['SB3_beat']})  "
          f"Δ原版 {detail['SA_vs_A']:+.2f}/{detail['SB_vs_B']:+.2f}/{detail['SB3_vs_B3']:+.2f}pp")
    pd.set_option("display.unicode.east_asian_width", True)
    pd.set_option("display.width", 460)
    show = df[["name", "bh",
               "A_ret", "As_ret", "SA_ret",
               "B_ret", "Bs_ret", "SB_ret",
               "B3_ret", "B3s_ret", "SB3_ret"]].copy()
    print(show.to_string(index=False))
    print(f"\n完成：{out_dir}（原版 trades_A/B/B3、强势版 trades_A/B/B3_strong、标准版 trades_StdA/StdB/StdB3、summary.json）")


if __name__ == "__main__":
    main()
