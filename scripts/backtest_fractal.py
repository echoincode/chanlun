# -*- coding: utf-8 -*-
"""缠论分型（顶/底）历史胜率回测 —— 只读独立脚本，不修改任何 pipeline 代码。

目的：
  1. 测量本系统分型识别算子产出的顶/底分型在A股个股上的基线胜率与前瞻收益；
  2. 逐维度（趋势状态/量比/20棒区间位置）计算条件胜率，检验哪些过滤维度真有预测力；
  3. 对比「可交易变体 V1（裸3K分型，检测收盘即可交易）」与
     「系统最终变体 V2（经 ±4 极值过滤 + 连续分型过滤，含未来函数）」，
     量化未来函数对历史统计的虚高程度。

样本口径：
  - 仅A股个股（000/001/002/003/300/301/600/601/603/605/688/689 开头），
    ETF/基金/北交所全部排除；
  - 排除 ST（以事件日期附近的 is_st 为准）与上市不足 300 根K线者；
  - 前复权日线；信号检测=右K线收盘（无前视），收益自检测收盘起算。

用法：
  python scripts/backtest_fractal.py [--sample N] [--max-stocks N]
输出：
  output/backtest/fractal_backtest_<日期>/report.html + 若干 CSV
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import random
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

STOCK_PREFIXES = ("000", "001", "002", "003",
                  "300", "301", "600", "601", "603", "605", "688", "689")
HORIZONS = (1, 3, 5, 10, 20)
FETCH_START = "20200601"     # 多取半年供均线预热
SIGNAL_START = "20210104"    # 信号统计起点
END = "20260908"
CHUNK = 200
NEED_BARS = 300              # 上市不足此数剔除


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def load_universe() -> list:
    """股票代码全集，按前缀过滤出沪深A股（自动排除ETF/北交所/指数）。"""
    r = sdk_rd.get("股票代码")
    codes = set()
    for k in r.keys():
        for c in r.get(k):
            c = str(c)
            if c.startswith(STOCK_PREFIXES):
                codes.add(c)
    return sorted(codes)


def rows_to_df(rows: list) -> pd.DataFrame | None:
    if not rows or len(rows) < NEED_BARS:
        return None
    df = pd.DataFrame(rows)
    df["datetime"] = df["date"]
    df = df.sort_values("datetime").reset_index(drop=True)
    keep = df[["datetime", "open", "high", "low", "close", "volume", "amount",
               "is_st", "name"]].copy()
    for col in ("open", "high", "low", "close", "volume", "amount"):
        keep[col] = pd.to_numeric(keep[col], errors="coerce")
    keep = keep.dropna(subset=["open", "high", "low", "close"])
    if len(keep) < NEED_BARS or keep["close"].le(0).any():
        return None
    return keep


def label_stock(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """用系统同一套算子打标。返回 (V1识别df, V2终选df)，均为合并后缠论K线。"""
    proc = ChanlunProcessor()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        trimmed = proc.trim_data_by_extremes(df)
        if trimmed.empty or len(trimmed) < 60:
            return None
        merged = proc.merge_klines(trimmed)
        if merged.empty or len(merged) < 60:
            return None
        v1 = proc.identify_fractals(merged)
        v2 = proc.process_fractals(merged)
    return v1, v2


def extract_events(tagged: pd.DataFrame, df_raw: pd.DataFrame,
                   code: str, name: str, variant: str) -> list:
    """把分型标记转为事件表：检测日=右K线收盘，条件只用检测日及以前的数据。"""
    n = len(tagged)
    if n < 40:
        return []
    close = tagged["close"].astype(float).values
    high = tagged["high"].astype(float).values
    low = tagged["low"].astype(float).values
    vol = pd.to_numeric(tagged["volume"], errors="coerce").fillna(0).values
    dates = tagged["datetime"].values
    ftype = tagged["fractal_type"].values
    isf = tagged["is_fractal"].values.astype(bool)

    sma20 = pd.Series(close).rolling(20).mean().values
    st_series = df_raw.set_index("datetime")["is_st"]

    events = []
    max_h = max(HORIZONS)
    for m in range(1, n - 1):
        if not isf[m] or ftype[m] not in ("top", "bottom"):
            continue
        d = m + 1                      # 检测日 = 右K线
        if d + max_h >= n:             # 需要完整 20 棒前瞻窗口
            continue
        dt = int(dates[d])
        if dt < int(SIGNAL_START):
            continue
        # ST 过滤：检测日往前最近的原始 is_st
        try:
            idx = st_series.index[st_series.index <= dt]
            if len(idx) and bool(st_series.loc[idx[-1]]):
                continue
        except Exception:
            pass

        ret = {}
        ok = True
        for h in HORIZONS:
            base = close[d]
            if base <= 0 or close[d + h] <= 0:
                ok = False
                break
            ret[h] = close[d + h] / base - 1
        if not ok:
            continue

        # ---- 条件维度（检测时点可得）----
        ma = sma20[d]
        if np.isnan(ma):
            continue
        regime = "收盘在MA20上" if close[d] >= ma else "收盘在MA20下"
        vol5 = np.mean(vol[max(0, m - 5):m]) if m >= 1 else np.nan
        vr = vol[m] / vol5 if vol5 and vol5 > 0 else np.nan
        vol_b = "量比缺失" if np.isnan(vr) else ("放量" if vr >= 1.2 else ("常量" if vr >= 0.8 else "缩量"))
        lo20 = np.min(low[max(0, m - 20):m + 1])
        hi20 = np.max(high[max(0, m - 20):m + 1])
        rng = hi20 - lo20
        pos = (close[d] - lo20) / rng if rng > 0 else np.nan
        pos_b = "位置缺失" if np.isnan(pos) else ("低区" if pos < 0.33 else ("中区" if pos < 0.67 else "高区"))

        events.append({
            "code": code, "name": name, "variant": variant,
            "type": ftype[m], "detect_date": dt,
            **{f"ret{h}": round(ret[h] * 100, 3) for h in HORIZONS},
            "regime": regime, "vol_bucket": vol_b, "pos_bucket": pos_b,
            "vol_ratio": round(float(vr), 2) if not np.isnan(vr) else None,
            "range_pos": round(float(pos), 3) if not np.isnan(pos) else None,
        })
    return events


def hit_rate(sub: pd.DataFrame, ftype: str, h: int) -> float:
    r = sub[f"ret{h}"]
    if ftype == "top":
        return float((r < 0).mean()) * 100
    return float((r > 0).mean()) * 100


def agg_stats(ev: pd.DataFrame, keys: list) -> pd.DataFrame:
    rows = []
    for k, sub in ev.groupby(keys, observed=True):
        row = dict(zip(keys, (k if isinstance(k, tuple) else (k,))))
        row["样本数"] = len(sub)
        for h in HORIZONS:
            row[f"胜率{h}d%"] = round(hit_rate(sub, row.get("type", sub["type"].iloc[0]), h), 1)
            row[f"均收益{h}d%"] = round(sub[f"ret{h}"].mean(), 2)
            row[f"中位{h}d%"] = round(sub[f"ret{h}"].median(), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def conditional_table(ev: pd.DataFrame, dim: str) -> pd.DataFrame:
    rows = []
    for ftype in ("top", "bottom"):
        base = ev[ev["type"] == ftype]
        if base.empty:
            continue
        b5 = hit_rate(base, ftype, 5)
        for val, sub in base.groupby(dim, observed=True):
            if len(sub) < 30:
                continue
            rows.append({
                "类型": "顶分型" if ftype == "top" else "底分型",
                "维度": dim, "取值": val, "样本数": len(sub),
                "胜率5d%": round(hit_rate(sub, ftype, 5), 1),
                "相对基线pp": round(hit_rate(sub, ftype, 5) - b5, 1),
                "均收益5d%": round(sub["ret5"].mean(), 2),
                "基线胜率5d%": round(b5, 1),
            })
    return pd.DataFrame(rows)


def build_report(out_dir: str, ev_all: pd.DataFrame, n_stocks: int,
                 skipped: int, elapsed: float) -> str:
    v1 = ev_all[ev_all["variant"] == "V1"]
    v2 = ev_all[ev_all["variant"] == "V2"]
    base = agg_stats(v1, ["type"])
    base["类型"] = base["type"].map({"top": "顶分型", "bottom": "底分型"})
    v1y = v1.copy()
    v1y["year"] = pd.to_datetime(v1y["detect_date"], format="%Y%m%d").dt.year
    year_tab = agg_stats(v1y, ["type", "year"])
    year_tab = year_tab.rename(columns={"year": "年份"})

    dims = ["regime", "vol_bucket", "pos_bucket"]
    cond_tabs = {d: conditional_table(v1, d) for d in dims}

    # V1 vs V2 对照（同股票同日期同类型配对）
    key_cols = ["code", "detect_date", "type"]
    merged = v1.merge(v2[key_cols].assign(in_v2=True), on=key_cols, how="left")
    keep_rate = float(merged["in_v2"].fillna(False).mean()) * 100
    kept = merged[merged["in_v2"] == True]  # noqa: E712
    cmp_rows = []
    for ftype in ("top", "bottom"):
        m1 = merged[merged["type"] == ftype]
        m2 = kept[kept["type"] == ftype]
        if len(m1) and len(m2):
            cmp_rows.append({
                "类型": "顶分型" if ftype == "top" else "底分型",
                "V1事件数": len(m1), "V2保留数": len(m2),
                "V2保留率%": round(len(m2) / len(m1) * 100, 1),
                "V1胜率5d%": round(hit_rate(m1, ftype, 5), 1),
                "V2胜率5d%": round(hit_rate(m2, ftype, 5), 1),
                "虚高pp": round(hit_rate(m2, ftype, 5) - hit_rate(m1, ftype, 5), 1),
            })
    cmp_tab = pd.DataFrame(cmp_rows)

    def df_to_html(d: pd.DataFrame) -> str:
        if d.empty:
            return "<p>（无数据）</p>"
        return d.to_html(index=False, border=0, classes="t",
                         justify="center", escape=False)

    year_tab_html = year_tab.copy()
    year_tab_html["类型"] = year_tab_html["type"].map({"top": "顶分型", "bottom": "底分型"})

    def stype(x):
        c = "pos" if x > 0 else "neg"
        return f'<span class="{c}">{x}</span>'

    disp = base.drop(columns=["type"]).copy()
    for c in [c for c in disp.columns if "收益" in c]:
        disp[c] = disp[c].map(stype)

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>缠论分型历史胜率回测报告</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1080px;margin:24px auto;padding:0 16px;color:#1f2329;font-size:14px}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px;border-left:4px solid #185FA5;padding-left:8px}}
table{{border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{border:1px solid #d9dce1;padding:5px 10px;text-align:center}}
th{{background:#f0f3f7}} .pos{{color:#C0392B}} .neg{{color:#1E8449}}
.note{{background:#FAF3E3;border:1px solid #E5D6A8;padding:10px 14px;border-radius:6px;font-size:13px}}
.meta{{color:#667;font-size:13px}}
</style></head><body>
<h1>缠论分型（顶/底）历史胜率回测报告</h1>
<p class="meta">样本：A股个股（已排除ETF/北交所/ST） {n_stocks} 只 ｜ 区间：{SIGNAL_START[:4]}-01 ~ {END[:4]}-09（前复权日线）｜ 信号：V1裸3K分型，右K线收盘确认，无前视 ｜ 耗时 {elapsed:.0f} 秒 ｜ 生成：{datetime.now():%Y-%m-%d %H:%M}</p>
<div class="note"><b>口径说明</b>：胜率N d = 分型右K线收盘后 N 根K线，收盘价涨跌方向与分型方向一致的比例（顶分型看跌、底分型看涨）。收益按检测日收盘起算，未计交易成本。条件维度均使用检测时点可得数据。</div>
<h2>一、基线：裸分型方向胜率（V1，可交易口径）</h2>
{df_to_html(disp)}
<h2>二、分年度胜率（V1）</h2>
{df_to_html(year_tab_html.drop(columns=["type"]))}
<h2>三、条件胜率：哪些过滤维度真有预测力（V1）</h2>
<p>「相对基线pp」为正表示该条件提升胜率，负表示反而更差。样本数&lt;30 的分组已剔除。</p>
<h3>1. 趋势状态（收盘相对 MA20）</h3>{df_to_html(cond_tabs['regime'])}
<h3>2. 分型当日量能（中间K量 / 前5K均量）</h3>{df_to_html(cond_tabs['vol_bucket'])}
<h3>3. 20棒区间位置（越低=跌得越深 / 越高=涨得越多）</h3>{df_to_html(cond_tabs['pos_bucket'])}
<h2>四、未来函数体检：V1（可交易）vs V2（系统最终输出，含±4极值过滤）</h2>
<p>V2 用了分型后 4 根K线的未来数据做标记，其统计不可以用于实盘预期；保留率越低、胜率虚高越多，说明历史回测若直接采用系统分型标记会严重失真。</p>
{df_to_html(cmp_tab)}
<p class="meta">剔除无法完整计算的股票：{skipped} 只。本报告由 scripts/backtest_fractal.py 自动生成，仅为统计研究，不构成投资建议。</p>
</body></html>"""

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    base.to_csv(os.path.join(out_dir, "baseline.csv"), index=False, encoding="utf-8-sig")
    for d, tab in cond_tabs.items():
        tab.to_csv(os.path.join(out_dir, f"cond_{d}.csv"), index=False, encoding="utf-8-sig")
    cmp_tab.to_csv(os.path.join(out_dir, "v1_vs_v2.csv"), index=False, encoding="utf-8-sig")
    ev_v1 = v1
    ev_v1.sample(min(5000, len(ev_v1)), random_state=7).to_csv(
        os.path.join(out_dir, "events_v1_sample.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"stocks": n_stocks, "events_v1": int(len(v1)),
                   "events_v2": int(len(v2)), "v2_keep_rate_pct": round(keep_rate, 1),
                   "elapsed_sec": round(elapsed, 1)}, f, ensure_ascii=False, indent=2)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="随机抽样N只（0=全市场）")
    ap.add_argument("--max-stocks", type=int, default=0)
    args = ap.parse_args()

    sdk_init(host="127.0.0.1", port=7899)
    universe = load_universe()
    random.seed(42)
    if args.sample:
        random.shuffle(universe)
        universe = universe[:args.sample]
    log(f"A股个股全集 {len(load_universe())} 只，本次回测 {len(universe)} 只")

    all_events = []
    skipped = 0
    t0 = time.time()
    for i in range(0, len(universe), CHUNK):
        chunk = universe[i:i + CHUNK]
        try:
            data = sdk_rd.get_data(chunk, start=FETCH_START, end=END,
                                   frequency="1d", fq="qfq")
        except Exception as e:
            log(f"chunk {i} 取数失败，跳过: {e}")
            continue
        for code in chunk:
            rows = data.get(code)
            df = rows_to_df(rows) if rows else None
            if df is None:
                skipped += 1
                continue
            name = str(df["name"].iloc[-1])
            try:
                labeled = label_stock(df)
            except Exception:
                skipped += 1
                continue
            if labeled is None:
                skipped += 1
                continue
            v1, v2 = labeled
            all_events.extend(extract_events(v1, df, code, name, "V1"))
            all_events.extend(extract_events(v2, df, code, name, "V2"))
        log(f"进度 {min(i + CHUNK, len(universe))}/{len(universe)} ｜ "
            f"事件 {len(all_events)} ｜ 耗时 {time.time() - t0:.0f}s")

    if not all_events:
        log("未产生任何事件，请检查数据接口")
        return
    ev = pd.DataFrame(all_events)
    out_dir = os.path.join(ROOT, "output", "backtest",
                           f"fractal_backtest_{datetime.now():%Y%m%d}")
    path = build_report(out_dir, ev, len(universe), skipped, time.time() - t0)
    log(f"完成：{path}")


if __name__ == "__main__":
    main()
