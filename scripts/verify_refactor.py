# -*- coding: utf-8 -*-
"""改造前置验证（只读，不修改任何 pipeline 代码）—— verify_refactor.py

对「分型更精准」三件事做改造前的对照验证，用持仓 10 只个股先行：
  实验1 尾部一致性：现状 V2 全过滤链的分型标记在「数据尾部截断 vs 全量」下
       会互相矛盾（今天标注、明天被删），量化不一致率；V1(裸3K+前向极值)
       通道作对照应≈0。
  实验2 结构特征 lift：对「被反向分型钉死的底部端点」事件逐个加候选特征
       （段长比 len_ratio / 笔段背驰 diverged / 盈亏比 rr），
       测每个特征「加 vs 不加」的 5/20 日胜率差。
  实验3 状态机分桶判别力：对每个裸底分型候选从出现日起逐日跟踪
       （破位→失效 / 收复中K高点→确认 / 否则待确认），
       比较三状态下的「未来5日收益」是否有区分度。
输出：output/backtest/verify_refactor_<日期>/ 下 CSV + summary.json，控制台打表。

口径：合并K线（与现有回测一致）；收益按合并K收盘起算、无前视；
      数据 = stockdb 前复权日线 2020~今（多取一年供预热）。
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

# 复用持仓回测脚本的取数与打标函数（避免重复实现）
from scripts.backtest_holdings_trade import (  # noqa: E402
    load_stock_holdings,
    rows_to_df as h_rows_to_df,
    build_merged,
    series_of,
    to_int8,
)

FETCH_START = "20200101"
END = "20260909"
NEED_BARS = 200
TAIL_MERGE = 30          # 实验1：尾部截断的合并K线数
BUFFER = 14              # 实验1：过滤链边界缓冲（对比区上界 = 截断点 - BUFFER）
FWD_H = (5, 10, 20)      # 前瞻窗口（合并K根数）
TRACK_DAYS = 21          # 实验3：每个候选底跟踪天数
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# 打标工具（全部走 ChanlunProcessor，与实盘同一套算子）
# --------------------------------------------------------------------------
def chain_v1(merged: pd.DataFrame) -> pd.DataFrame:
    """V1 = 裸 3K 分型（只读通道，无 ±4 未来过滤）。"""
    proc = ChanlunProcessor()
    with contextlib.redirect_stdout(io.StringIO()):
        return proc.identify_fractals(merged)


def chain_v2(merged: pd.DataFrame) -> pd.DataFrame:
    """V2 = 现状完整过滤链（±4 极值 + 连续 + 关系验证 + 接近分型 + 迭代）。"""
    proc = ChanlunProcessor()
    with contextlib.redirect_stdout(io.StringIO()):
        return proc.process_fractals(merged)


def build_pipeline(df_raw: pd.DataFrame):
    """trim → merge，返回 (trimmed, merged)。失败返回 None。"""
    proc = ChanlunProcessor()
    with contextlib.redirect_stdout(io.StringIO()):
        trimmed = proc.trim_data_by_extremes(df_raw)
        if trimmed.empty or len(trimmed) < 60:
            return None
        merged = proc.merge_klines(trimmed)
        if merged.empty or len(merged) < 60:
            return None
    return trimmed, merged


def events_set(tagged: pd.DataFrame, hi: int) -> dict:
    """取 tagged 在 [0, hi] 区间的分型事件集 {date: type}。"""
    out = {}
    n = len(tagged)
    for i in range(1, n - 1):
        if i > hi:
            break
        if not tagged.loc[i, "is_fractal"]:
            continue
        ty = tagged.loc[i, "fractal_type"]
        if ty in ("top", "bottom"):
            out[to_int8(tagged.loc[i, "datetime"])] = ty
    return out


def merge_consistency(merged_full: pd.DataFrame, v1_full: pd.DataFrame):
    """实验1：截尾(prefix) 链 vs 全量链在共同区间的标记一致性。

    返回 dict：
      v1: {total, changed}  裸3K 通道（应≈0 不一致，作 sanity）
      v2: {total, changed}  现状全过滤链（量化「今天标明天删」）
    """
    cut_at = len(merged_full) - TAIL_MERGE
    if cut_at < BUFFER + 80:
        return None
    region_hi = cut_at - BUFFER
    prefix = merged_full.iloc[:cut_at].copy()

    # V1 对照（局部 3K，理应完全一致）
    v1p = chain_v1(prefix)
    s1f = events_set(v1_full, region_hi)
    s1p = events_set(v1p, region_hi)

    # V2 现状链
    v2f = chain_v2(merged_full)
    v2p = chain_v2(prefix)
    s2f = events_set(v2f, region_hi)
    s2p = events_set(v2p, region_hi)

    def diff(a: dict, b: dict) -> tuple[int, int]:
        """a=全量定稿, b=截尾可见。返回 (全量事件数, 截尾与全量不一致数)。"""
        if not a:
            return 0, 0
        chg = 0
        for dt, ty in a.items():
            if b.get(dt) != ty:      # 截尾没标 / 标了不同类型
                chg += 1
        return len(a), chg

    return {
        "v1": diff(s1f, s1p),
        "v2": diff(s2f, s2p),
    }


# --------------------------------------------------------------------------
# 实验2：结构特征 lift（事件 = 被反向分型钉死的底部端点）
# --------------------------------------------------------------------------
def macd_hist_series(closes: np.ndarray) -> np.ndarray:
    n = len(closes)
    out = np.zeros(n)
    if n < MACD_SLOW + MACD_SIGNAL + 5:
        return out
    c = closes.astype(float)
    ema_f = pd.Series(c).ewm(span=MACD_FAST, adjust=False).mean().values
    ema_s = pd.Series(c).ewm(span=MACD_SLOW, adjust=False).mean().values
    dif = ema_f - ema_s
    dea = pd.Series(dif).ewm(span=MACD_SIGNAL, adjust=False).mean().values
    out = (dif - dea) * 2.0
    return out


def pinned_endpoints(s: dict) -> list:
    """在线滚动（同向更强替换、反向钉死），返回被钉死端点列表。

    每项 dict: i=端点中Kindex, t=type, nail=钉死它的反向分型中Kindex。
    端点交替排列：t0,b0,t1,b1,...（首个由首个候选决定）。
    """
    n = s["n"]
    pend_t, pend_i = None, -1
    eps = []
    for i in range(1, n - 1):
        ty = s["ftype"][i]
        if ty is None:
            continue
        if pend_t is None:
            pend_t, pend_i = ty, i
            continue
        if ty == pend_t:
            better = ((ty == "top" and s["high"][i] >= s["high"][pend_i]) or
                      (ty == "bottom" and s["low"][i] <= s["low"][pend_i]))
            if better:
                pend_t, pend_i = ty, i
            continue
        # 反向出现 → 钉死 pend
        eps.append({"i": pend_i, "t": pend_t, "nail": i})
        pend_t, pend_i = ty, i
    return eps


def seg_events(s: dict, eps: list) -> list:
    """把钉死端点序列转成「底部买入事件」，全部信息在确认时点可得。

    对底部端点 b_k（其下跌笔起点为 t_k），被下一个顶部端点钉死：
      confirm = nail.top.i + 1（右K收盘日），收益自 confirm 起算。
    返回每事件 dict: code/index/date/confirm + 特征与前瞻收益。
    """
    n = s["n"]
    hi = s["high"].astype(float) if not isinstance(s["high"], np.ndarray) else s["high"]
    lo = s["low"].astype(float) if not isinstance(s["low"], np.ndarray) else s["low"]
    cl = s["close"].astype(float) if not isinstance(s["close"], np.ndarray) else s["close"]
    mh = macd_hist_series(cl)

    evs = []
    # 端点交替；找 (top, bottom) 相邻对作为下跌笔
    for k in range(len(eps) - 1):
        a, b = eps[k], eps[k + 1]
        if not (a["t"] == "top" and b["t"] == "bottom"):
            continue
        # b 是下跌笔终点（底），需被后续顶钉死才成已确认底部事件
        # eps 中 b 的后续 = k+2（应为 top 且其 nail 在 b 之后）→ 钉死 b 的即 k+2
        nailer = eps[k + 2] if k + 2 < len(eps) else None
        if nailer is None or nailer["t"] != "top":
            continue
        confirm = nailer["i"] + 1          # 钉死 b 的顶分型 右K收盘
        if confirm + max(FWD_H) >= n:
            continue
        if confirm <= a["i"]:
            continue
        base = cl[confirm]
        if base <= 0:
            continue
        # ---- 特征（确认时点可得）----
        cur_len = b["i"] - a["i"]          # 本下跌笔长（顶→底）
        entry = base
        stop = lo[b["i"]]
        target = hi[a["i"]]                # 回到下跌笔起点（前顶）
        rr = (target - entry) / (entry - stop) if (entry - stop) > 0 else np.nan
        # 前一段下跌笔（若端点从 top 起且 k>=2：eps[k-2]=t_{k-1}, eps[k-1]=b_{k-1}）
        len_ratio = np.nan
        diverged = np.nan
        if k >= 2 and eps[k - 2]["t"] == "top" and eps[k - 1]["t"] == "bottom":
            plen = eps[k - 1]["i"] - eps[k - 2]["i"]
            if plen > 0:
                len_ratio = cur_len / plen
            # 笔段力度（macd 柱段内和，下跌段为负）
            f_prev = float(np.sum(mh[eps[k - 2]["i"]:eps[k - 1]["i"] + 1]))
            f_cur = float(np.sum(mh[a["i"]:b["i"] + 1]))
            if f_cur < 0 and f_prev < 0:
                diverged = f_cur > f_prev      # 负得更少 = 力度衰竭 = 背驰
        ev = {
            "index": b["i"], "date": to_int8(s["d8"][confirm]), "confirm": confirm,
            "len_ratio": len_ratio, "diverged": diverged, "rr": rr,
        }
        ok = True
        for h in FWD_H:
            if cl[confirm + h] <= 0:
                ok = False
                break
            ev[f"fwd{h}"] = cl[confirm + h] / base - 1
        if ok:
            evs.append(ev)
    return evs


def lift_table(evs: list) -> pd.DataFrame:
    if not evs:
        return pd.DataFrame()
    df = pd.DataFrame(evs)
    rows = []
    base_all = df
    for h in (5, 20):
        b_all = float((base_all[f"fwd{h}"] > 0).mean()) * 100

        def cond(label, col, mask):
            sub = df[mask & df[col].notna()]
            base_nn = df[df[col].notna()]
            b_nn = float((base_nn[f"fwd{h}"] > 0).mean()) * 100
            c = float((sub[f"fwd{h}"] > 0).mean()) * 100
            rows.append({
                "特征": label, "窗口": f"{h}d", "条件样本": len(sub),
                "特征非空样本": len(base_nn),
                "基线(全事件)%": round(b_all, 1),
                "基线(非空)%": round(b_nn, 1),
                "条件胜率%": round(c, 1),
                "lift vs 非空pp": round(c - b_nn, 1),
                "条件均收益%": round(float(sub[f"fwd{h}"].mean() * 100), 2),
            })

        cond("len_ratio<=0.8", "len_ratio", df["len_ratio"] <= 0.8)   # 当前下跌段更短
        cond("diverged", "diverged", df["diverged"] == True)          # 笔段背驰
        cond("rr>=2", "rr", df["rr"] >= 2)                            # 盈亏比达标
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 实验3：状态机分桶判别力（事件 = 裸底分型候选，从出现日逐日跟踪）
# --------------------------------------------------------------------------
def state_rows(s: dict, code: str) -> pd.DataFrame:
    n = s["n"]
    lo = s["low"].astype(float) if not isinstance(s["low"], np.ndarray) else s["low"]
    hi = s["high"].astype(float) if not isinstance(s["high"], np.ndarray) else s["high"]
    cl = s["close"].astype(float) if not isinstance(s["close"], np.ndarray) else s["close"]
    rows = []
    for m in range(1, n - 1):
        if s["ftype"][m] != "bottom":
            continue
        d = m + 1                            # 右K收盘 = 候选可见日
        if d + max(FWD_H) >= n:
            continue
        fract_low, mid_high = lo[m], hi[m]
        state = "pending"
        ever_confirmed = False
        for k in range(d, min(n - max(FWD_H), d + TRACK_DAYS)):
            if cl[k] < fract_low:            # 破位优先 → 失效
                state = "invalidated"
            elif not ever_confirmed and cl[k] > mid_high:
                ever_confirmed = True
                state = "confirmed"
            else:
                state = state if state == "invalidated" else (
                    "confirmed" if ever_confirmed else "pending")
            base = cl[k]
            if base <= 0:
                continue
            f5 = cl[k + 5] / base - 1 if cl[k + 5] > 0 else np.nan
            rows.append({"code": code, "state": state,
                         "fwd5": f5, "k_off": k - d})
    return pd.DataFrame(rows)


def state_table(rows_all: pd.DataFrame) -> pd.DataFrame:
    if rows_all is None or rows_all.empty:
        return pd.DataFrame()
    g = rows_all.dropna(subset=["fwd5"]).groupby("state")["fwd5"]
    out = pd.DataFrame({
        "状态": g.count().index,
        "样本(日×事件)": g.count().values,
        "未来5日均收益%": (g.mean().values * 100).round(2),
        "未来5日中位%": (g.median().values * 100).round(2),
        "上涨占比%": (g.apply(lambda x: (x > 0).mean() * 100)).round(1).values,
    })
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------
def main() -> None:
    holdings = load_stock_holdings()
    log(f"持仓个股 {len(holdings)} 只: {[n for _, n in holdings]}")
    sdk_init(host="127.0.0.1", port=7899)
    t0 = time.time()

    cons_rows, seg_all, st_rows = [], [], None
    removed = {"extremes": 0, "consec": 0, "final": 0, "n1": 0}

    for code, name in holdings:
        df = None
        # stockdb 取数间歇性返回空（实测同参数 ~1/3 概率 n=0），空也要重试+退避
        for attempt in range(6):
            try:
                d0 = sdk_rd.get_data([code], start=FETCH_START, end=END,
                                     frequency="1d", fq="qfq")
                rows = d0.get(code) if d0 and isinstance(d0, dict) else None
                df = h_rows_to_df(rows) if rows else None
                if df is not None:
                    break
            except Exception:
                df = None
            time.sleep(1.5 * (attempt + 1))
        if df is None:
            log(f"跳过 {code} {name}: 取数连续失败/为空")
            continue

        pipe = build_pipeline(df)
        if pipe is None:
            log(f"跳过 {code} {name}: 无法构建合并K线")
            continue
        _, merged = pipe
        v1tag = chain_v1(merged)                 # V1 打标：series_of 与一致性共用
        s = series_of(v1tag)

        # --- 实验1：尾部一致性 ---
        con = merge_consistency(merged, v1tag)
        if con:
            cons_rows.append({
                "name": name, "code": code,
                "v1_事件": con["v1"][0], "v1_不一致": con["v1"][1],
                "v2_事件": con["v2"][0], "v2_不一致": con["v2"][1],
            })

        # --- 逐过滤段删除率（V2 链 vs V1）---
        v2tag = chain_v2(merged)
        n1 = int(v1tag["is_fractal"].sum())
        n_fin = int(v2tag["is_fractal"].sum())
        removed["n1"] += n1
        removed["extremes_consec_final"] = removed.get(
            "extremes_consec_final", 0) + (n1 - n_fin)
        removed["final"] += n_fin

        # --- 实验2：底部确认端点特征 lift ---
        eps = pinned_endpoints(s)
        evs = seg_events(s, eps)
        for e in evs:
            e.update({"name": name, "code": code})
        seg_all.extend(evs)

        # --- 实验3：状态机分桶 ---
        sr = state_rows(s, code)
        st_rows = sr if st_rows is None else pd.concat([st_rows, sr], ignore_index=True)
        log(f"{name} {code}: 合并K={len(merged)} V1分型={n1} V2定稿={n_fin} "
            f"底部确认事件={len(evs)}")

    # ================= 汇总输出 =================
    out_dir = os.path.join(ROOT, "output", "backtest",
                           f"verify_refactor_{datetime.now():%Y%m%d}")
    os.makedirs(out_dir, exist_ok=True)

    # 表1a 过滤链删除率
    n1 = removed["n1"]
    fin = removed["final"]
    tab1a = pd.DataFrame([{
        "V1裸分型总数": n1,
        "V2定稿总数": fin,
        "V2保留率%": round(fin / n1 * 100, 1) if n1 else None,
        "被过滤删除%": round((n1 - fin) / n1 * 100, 1) if n1 else None,
    }])

    # 表1b 尾部一致性
    tab1b = pd.DataFrame(cons_rows)
    if not tab1b.empty:
        for v in ("v1", "v2"):
            tab1b[f"{v}_不一致率%"] = (
                tab1b[f"{v}_不一致"] / tab1b[f"{v}_事件"] * 100).round(2)
        tab1b[""] = tab1b["name"]

    # 表2 特征 lift
    tab2 = lift_table(seg_all)

    # 表3 状态机
    tab3 = state_table(st_rows)

    pd.set_option("display.unicode.east_asian_width", True)
    pd.set_option("display.width", 240)
    print("\n======== 实验1a 现状过滤链的删除力度（合并K分型）========")
    print(tab1a.to_string(index=False))
    print("\n======== 实验1b 尾部一致性：截尾 vs 全量（共同区间）========")
    print("指标含义：全量定稿中有多少分型在「截至更早日期的数据」上 缺失/类型不同")
    if not tab1b.empty:
        print(tab1b[["name", "v1_事件", "v1_不一致", "v1_不一致率%",
                     "v2_事件", "v2_不一致", "v2_不一致率%"]].to_string(index=False))
        m1 = tab1b["v1_不一致率%"].mean()
        m2 = tab1b["v2_不一致率%"].mean()
        print(f"平均：V1(裸3K) 不一致率 {m1:.2f}% ｜ V2(现状链) 不一致率 {m2:.2f}%")
    else:
        print("（无数据）")
    print("\n======== 实验2 结构特征 lift（底部确认事件；>0 说明特征有增益）========")
    if not tab2.empty:
        print(tab2.to_string(index=False))
    else:
        print("（无数据）")
    print("\n======== 实验3 状态机分桶判别力（底分型候选逐日跟踪）========")
    if tab3 is not None and not tab3.empty:
        print(tab3.to_string(index=False))
        mean_p = float(st_rows[st_rows["state"] == "pending"]["fwd5"].mean() * 100)
        mean_c = float(st_rows[st_rows["state"] == "confirmed"]["fwd5"].mean() * 100)
        mean_i = float(st_rows[st_rows["state"] == "invalidated"]["fwd5"].mean() * 100)
        print(f"确认−待确认 = {mean_c - mean_p:+.2f}pp ｜ 待确认−失效 = {mean_p - mean_i:+.2f}pp")
    else:
        print("（无数据）")

    tab1a.to_csv(os.path.join(out_dir, "t1_filter_strength.csv"),
                 index=False, encoding="utf-8-sig")
    if not tab1b.empty:
        tab1b.to_csv(os.path.join(out_dir, "t1_tail_consistency.csv"),
                     index=False, encoding="utf-8-sig")
    if not tab2.empty:
        tab2.to_csv(os.path.join(out_dir, "t2_feature_lift.csv"),
                    index=False, encoding="utf-8-sig")
    if tab3 is not None and not tab3.empty:
        tab3.to_csv(os.path.join(out_dir, "t3_state_bucket.csv"),
                    index=False, encoding="utf-8-sig")
    summary = {
        "stocks": len(holdings),
        "v1_total": n1, "v2_final": fin,
        "bottom_events": len(seg_all),
        "state_rows": 0 if st_rows is None else len(st_rows),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"完成：{out_dir} ｜ 耗时 {summary['elapsed_sec']}s")


if __name__ == "__main__":
    main()
