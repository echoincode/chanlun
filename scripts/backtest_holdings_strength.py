# -*- coding: utf-8 -*-
"""验证：给缠论顶底分型打「强弱」标签后，只做强势分型能否提升方案 A 胜率。

完全复用 backtest_holdings_trade 的识别与回测引擎（build_merged / series_of /
events_backward / simulate），不改动任何 pipeline 核心代码。仅在事件层叠加一个
"强弱过滤"：

  强弱定义（标准缠论分型强弱，按第1根K是否先突破）：
    - 顶分型 strong = 第1根 high >= 第3根 high（第1根即封顶/突破，反转果断）
               weak  = 第3根 high  >  第1根 high（第3根仍创新高，顶未成/中继）
    - 底分型 strong = 第1根 low  <= 第3根 low（第1根即探底）
               weak  = 第3根 low  <  第1根 low（第3根仍创新低）
    （第1根==第3根 记为 medium，实际几乎不出现，故 nonweak≈strong）

方案：
  A_all / A_strong / A_nonweak   —— 后向窗口，分别不过滤 / 仅 strong / 排除 weak
  B_all / B_strong               —— 在线滚动，作对照

输出：output/backtest/holdings_strength_<日期>/summary.json + 各方案 trades_*.csv
（本轮不生成 HTML，仅 CSV + 控制台表格）
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.environ.get("STOCKDB_SDK_PATH", r"D:\stockdb\pybao"))

from stock_sdk import init as sdk_init, rd as sdk_rd  # noqa: E402
import backtest_holdings_trade as bt  # noqa: E402

SIGNAL_START = bt.SIGNAL_START
BK = bt.BK
MIN_GAP = bt.MIN_GAP


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def classify_strength(tagged: pd.DataFrame) -> list:
    """返回与 tagged 行对齐的 strength 列表：None / 'strong' / 'weak'。

    优先读取核心 identify_fractals 已算好的 fractal_strength 列（端到端验证用），
    缺失时回退自算（逻辑与核心一致：第1根K是否先突破）。
    """
    n = len(tagged)
    strength = [None] * n
    col = tagged.get("fractal_strength")
    if col is not None:
        for i in range(n):
            v = col.iloc[i]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                strength[i] = None
            else:
                strength[i] = str(v)
        return strength
    # 回退：自算（与核心逻辑一致）
    hi = tagged["high"].astype(float).values
    lo = tagged["low"].astype(float).values
    ft = tagged["fractal_type"].values
    isf = tagged["is_fractal"].values.astype(bool)
    for i in range(1, n - 1):
        if not isf[i] or ft[i] not in ("top", "bottom"):
            continue
        if ft[i] == "top":
            strength[i] = "strong" if hi[i - 1] >= hi[i + 1] else "weak"
        else:  # bottom
            strength[i] = "strong" if lo[i - 1] <= lo[i + 1] else "weak"
    return strength


def series_with_strength(tagged: pd.DataFrame) -> dict:
    s = bt.series_of(tagged)
    s["strength"] = classify_strength(tagged)
    return s


def strength_ok(st: str | None, mode: str) -> bool:
    if mode == "all":
        return True
    if mode == "strong":
        return st == "strong"
    if mode == "nonweak":
        return st in ("strong", "medium")
    return True


def events_backward_strong(s: dict, strength_mode: str = "all") -> list:
    """方案A + 强弱过滤。strong_mode: all / strong / nonweak。"""
    ev = []
    n, d8 = s["n"], s["d8"]
    for i in range(BK, n - 2):
        typ = s["ftype"][i]
        if typ is None:
            continue
        if not strength_ok(s["strength"][i], strength_mode):
            continue
        exe = i + 2
        if exe >= n or d8[exe] < SIGNAL_START:
            continue
        if typ == "top" and s["high"][i] < max(s["high"][i - BK:i]):
            continue
        if typ == "bottom" and s["low"][i] > min(s["low"][i - BK:i]):
            continue
        ev.append((exe, typ))
    return ev


def events_rolling_strong(s: dict, min_gap: int | None = None,
                          strength_mode: str = "all") -> list:
    """方案B + 强弱过滤（候选与钉死信号均按 strength_mode 把关）。"""
    ev = []
    n, d8 = s["n"], s["d8"]
    pend_t, pend_i = None, -1

    def set_pend(typ, i):
        nonlocal pend_t, pend_i
        if strength_ok(s["strength"][i], strength_mode):
            pend_t, pend_i = typ, i
        else:
            pend_t, pend_i = None, -1

    for i in range(1, n - 1):
        typ = s["ftype"][i]
        if typ is None:
            continue
        if d8[i + 1] < SIGNAL_START:
            continue
        if pend_t is None:
            set_pend(typ, i)
            continue
        if typ == pend_t:
            better = ((typ == "top" and s["high"][i] >= s["high"][pend_i]) or
                      (typ == "bottom" and s["low"][i] <= s["low"][pend_i]))
            if better:
                set_pend(typ, i)   # 仅当当前分型强度达标才更新候选
            continue
        # 反向出现
        if min_gap is not None and (i - pend_i) < min_gap:
            set_pend(typ, i)
            continue
        # 间距达标 → 钉死 pend（钉死信号强度也需达标）
        if strength_ok(s["strength"][pend_i], strength_mode):
            exe = i + 2
            if exe < n and d8[exe] >= SIGNAL_START:
                ev.append((exe, pend_t))
        set_pend(typ, i)
    return ev


def main() -> None:
    holdings = bt.load_stock_holdings()
    log(f"持仓个股 {len(holdings)} 只: {[n for _, n in holdings]}")
    sdk_init(host="127.0.0.1", port=7899)
    t0 = time.time()

    variants = ["A_all", "A_strong", "A_nonweak", "B_all", "B_strong"]
    all_tr = {v: [] for v in variants}
    rows = []

    for code, name in holdings:
        rdf = bt.rows_to_df(bt.fetch_one(code))
        if rdf is None:
            log(f"跳过 {code} {name}: 数据不足")
            continue
        tagged = bt.build_merged(rdf)
        if tagged is None:
            log(f"跳过 {code} {name}: 无法构建合并K线")
            continue
        s = series_with_strength(tagged)

        sims = {
            "A_all":    bt.simulate(events_backward_strong(s, "all"), s, code, name),
            "A_strong": bt.simulate(events_backward_strong(s, "strong"), s, code, name),
            "A_nonweak": bt.simulate(events_backward_strong(s, "nonweak"), s, code, name),
            "B_all":    bt.simulate(events_rolling_strong(s, None, "all"), s, code, name),
            "B_strong": bt.simulate(events_rolling_strong(s, None, "strong"), s, code, name),
        }
        if any(v is None for v in sims.values()):
            log(f"跳过 {code} {name}: 起点不足")
            continue
        for v in variants:
            all_tr[v].extend(sims[v]["trades"])

        rows.append({
            "name": name, "code": code, "bh": sims["A_all"]["bh_ret_pct"],
            "A_all_n": sims["A_all"]["n_trades"], "A_all_win": sims["A_all"]["win_rate"],
            "A_all_ret": sims["A_all"]["ret_pct"], "A_all_ex": sims["A_all"]["excess_pct"],
            "A_strong_n": sims["A_strong"]["n_trades"], "A_strong_win": sims["A_strong"]["win_rate"],
            "A_strong_ret": sims["A_strong"]["ret_pct"], "A_strong_ex": sims["A_strong"]["excess_pct"],
            "A_nonweak_n": sims["A_nonweak"]["n_trades"], "A_nonweak_win": sims["A_nonweak"]["win_rate"],
            "A_nonweak_ret": sims["A_nonweak"]["ret_pct"], "A_nonweak_ex": sims["A_nonweak"]["excess_pct"],
            "B_all_ret": sims["B_all"]["ret_pct"], "B_all_win": sims["B_all"]["win_rate"],
            "B_strong_ret": sims["B_strong"]["ret_pct"], "B_strong_win": sims["B_strong"]["win_rate"],
        })
        log(f"{name}: A全={sims['A_all']['ret_pct']:+.1f}%({sims['A_all']['n_trades']}) "
            f"强={sims['A_strong']['ret_pct']:+.1f}%({sims['A_strong']['n_trades']}) "
            f"非弱={sims['A_nonweak']['ret_pct']:+.1f}%({sims['A_nonweak']['n_trades']}) "
            f"| B全={sims['B_all']['ret_pct']:+.1f}% B强={sims['B_strong']['ret_pct']:+.1f}% "
            f"BH={sims['A_all']['bh_ret_pct']:+.1f}%")

    if not rows:
        log("无任何有效标的")
        return

    df = pd.DataFrame(rows)

    def avg(k):
        return float(df[k].mean())

    # 汇总胜率（总盈利笔/总笔，跨标的池化）
    def pooled(v):
        tr = all_tr[v]
        if not tr:
            return None, 0
        w = sum(1 for t in tr if t["ret_pct"] > 0)
        return round(w / len(tr) * 100, 1), len(tr)

    detail = {
        "stocks": len(rows),
        "BH_avg": avg("bh"),
        "A_all_avg": avg("A_all_ret"), "A_strong_avg": avg("A_strong_ret"),
        "A_nonweak_avg": avg("A_nonweak_ret"),
        "A_all_beat": int((df["A_all_ex"] > 0).sum()),
        "A_strong_beat": int((df["A_strong_ex"] > 0).sum()),
        "A_nonweak_beat": int((df["A_nonweak_ex"] > 0).sum()),
        "A_strong_vs_A": avg("A_strong_ret") - avg("A_all_ret"),
        "A_nonweak_vs_A": avg("A_nonweak_ret") - avg("A_all_ret"),
        "A_all_win_pooled": pooled("A_all")[0], "A_all_n_pooled": pooled("A_all")[1],
        "A_strong_win_pooled": pooled("A_strong")[0], "A_strong_n_pooled": pooled("A_strong")[1],
        "A_nonweak_win_pooled": pooled("A_nonweak")[0], "A_nonweak_n_pooled": pooled("A_nonweak")[1],
        "B_all_avg": avg("B_all_ret"), "B_strong_avg": avg("B_strong_ret"),
        "B_strong_vs_B": avg("B_strong_ret") - avg("B_all_ret"),
    }

    out_dir = os.path.join(ROOT, "output", "backtest",
                           f"holdings_strength_{datetime.now():%Y%m%d}")
    os.makedirs(out_dir, exist_ok=True)
    csv_map = (("A_all", "trades_A_all.csv"), ("A_strong", "trades_A_strong.csv"),
               ("A_nonweak", "trades_A_nonweak.csv"),
               ("B_all", "trades_B_all.csv"), ("B_strong", "trades_B_strong.csv"))
    for k, fn in csv_map:
        pd.DataFrame(all_tr[k]).to_csv(os.path.join(out_dir, fn),
                                       index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2)

    print("\n=== 组合汇总（等权平均；后向窗口 A 叠加分型强弱过滤）===")
    print(f"买入持有均值        {detail['BH_avg']:+.2f}%")
    print(f"A 全部分型          {detail['A_all_avg']:+.2f}%  "
          f"(跑赢BH {detail['A_all_beat']}/{len(rows)} | 池化胜率 {detail['A_all_win_pooled']}% / {detail['A_all_n_pooled']}笔)")
    print(f"A 仅强势分型        {detail['A_strong_avg']:+.2f}%  "
          f"(跑赢BH {detail['A_strong_beat']}/{len(rows)} | 池化胜率 {detail['A_strong_win_pooled']}% / {detail['A_strong_n_pooled']}笔)  "
          f"Δvs全={detail['A_strong_vs_A']:+.2f}pp")
    print(f"A 排除弱势(中继)    {detail['A_nonweak_avg']:+.2f}%  "
          f"(跑赢BH {detail['A_nonweak_beat']}/{len(rows)} | 池化胜率 {detail['A_nonweak_win_pooled']}% / {detail['A_nonweak_n_pooled']}笔)  "
          f"Δvs全={detail['A_nonweak_vs_A']:+.2f}pp")
    print(f"B 全部分型          {detail['B_all_avg']:+.2f}%")
    print(f"B 仅强势分型        {detail['B_strong_avg']:+.2f}%  Δvs全={detail['B_strong_vs_B']:+.2f}pp")

    pd.set_option("display.unicode.east_asian_width", True)
    pd.set_option("display.width", 360)
    print("\n--- 分标的明细（A方案：全 / 强 / 非弱；收益% 与 胜率% / 笔数）---")
    show = df[["name", "bh",
               "A_all_ret", "A_all_win", "A_all_n",
               "A_strong_ret", "A_strong_win", "A_strong_n",
               "A_nonweak_ret", "A_nonweak_win", "A_nonweak_n",
               "B_all_ret", "B_strong_ret"]].copy()
    print(show.to_string(index=False))
    print(f"\n完成：{out_dir}（trades_A_all/strong/nonweak、trades_B_all/strong、summary.json）"
          f"  耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
