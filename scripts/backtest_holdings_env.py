# -*- coding: utf-8 -*-
"""持仓个股：方案A + 方向1(市场环境) + 方向2(个股趋势) + 方向4(硬止损) —— 阶梯对照回测。

只读独立脚本，不修改任何 pipeline 代码。信号引擎复用 backtest_holdings_trade.py
的方案A（后向窗口：3K 形态 + 前 4 根极值确认，右K收盘即确认、无未来函数）。

方案阶梯（每层只加一个变量，可单独归因）：
  A0 = 原方案A基准（无任何新过滤）
  A1 = A0 + 方向1 市场环境「超跌风险闸门」：沪深300 状态判定（close vs MA20 +
       MA20斜率，3 日确认防抖）。注意 A 股「熊长牛短」——严格下行禁买会覆盖约
       45% 交易日、清空结构性反弹机会，故只禁「下行 且 close 乖离率 ≤ -2%」的
       系统性急跌区（约 16% 交易日），贴 MA20 的下行震荡保留交易。
  A2 = A1 + 方向2 个股趋势：个股合并K线序列同法判态——
       空头状态禁买底分型（防个股接飞刀）；多头状态顶分型不清仓（防踏空，交止损兜底）
  A3 = A2 + 方向4 硬止损：持仓中收盘价 <= 买入开盘价 × (1-10%) → 次日开盘离场

交易规则（与历次一致）：确认底分型→次日开盘全仓买、确认顶分型→次日开盘清仓卖
（A2 多头状态除外）；初始空仓、只做多、全仓切换；A股 T+1（确认右K收盘→下一交易
开盘成交，即实际最早可成交价）；费用：买万2.5、卖万2.5+印花税0.05%。
标的：仅持仓 A 股个股 10 只（holdings_list.py type=="stock"，ETF 排除）。

指数数据：data/index_daily_hs300.csv（pytdx 拉取 2016-10~今，前复权不适用指数用不复权）。
用法：python scripts/backtest_holdings_env.py
输出：output/backtest/holdings_env_<日期>/summary.json + trades_A0..A3.csv（不生成 HTML）
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
sys.path.insert(0, os.environ.get("STOCKDB_SDK_PATH", r"D:\stockdb\pybao"))

from stock_sdk import init as sdk_init, rd as sdk_rd  # noqa: E402
from scripts.backtest_holdings_trade import (  # noqa: E402
    END, SIGNAL_START, BUY_FEE, SELL_FEE,
    load_stock_holdings, to_int8, rows_to_df, build_merged, series_of,
    events_backward, log,
)

INDEX_CSV = os.path.join(ROOT, "data", "index_daily_hs300.csv")
FETCH_START = "20200101"   # 与历次一致：多取供合并K线/预热
ENV_CONFIRM = 3            # 环境状态切换需连续 N 日同向才生效（防抖）
STOP_LOSS = 0.10           # 方向4：收盘较买入开盘价回撤 10% 无条件离场
MA_FAST = 20
MA_SLOPE_LOOK = 5
BEAR_SKEW = 0.02           # 方向1：仅当市场「下行 且 乖离率<=-2%」(系统性急跌) 才禁买底分型


def _trend_states(closes, confirm: int = ENV_CONFIRM) -> list:
    """三态趋势判定：close>MA20 且 MA20 上行=up；close<MA20 且 MA20 下行=down；否则 neutral。

    返回与输入等长的状态列表（含 confirm 日防抖：连续 confirm 日同向才切换，防毛刺）。
    """
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    ma = pd.Series(closes).rolling(MA_FAST, min_periods=MA_FAST).mean().values
    slope = pd.Series(ma).diff(MA_SLOPE_LOOK).values
    raw = []
    for i in range(n):
        if np.isnan(ma[i]) or np.isnan(slope[i]):
            raw.append("neutral")
        elif closes[i] > ma[i] and slope[i] > 0:
            raw.append("up")
        elif closes[i] < ma[i] and slope[i] < 0:
            raw.append("down")
        else:
            raw.append("neutral")
    # 防抖：只有连续 confirm 根同向才切换；期间反向抖动会重置计数
    cur, cnt, pend = raw[0], 0, None
    out = []
    for st in raw:
        if st == cur:
            cnt, pend = 0, None
        else:
            if pend != st:
                pend, cnt = st, 1
            else:
                cnt += 1
                if cnt >= confirm:
                    cur, cnt, pend = st, 0, None
        out.append(cur)
    return out


def load_mkt_states(path: str = INDEX_CSV):
    """读取沪深300日线 → (date_i升序数组, 状态数组, 乖离率数组)。
    date_i=YYYYMMDD int；乖离率 = close/MA20 - 1（用于超跌闸门判定）。"""
    df = pd.read_csv(path)
    df["date_i"] = df["date"].astype(str).str.replace("-", "", regex=False).astype(int)
    df = df.sort_values("date_i").reset_index(drop=True)
    closes = df["close"].astype(float).values
    states = _trend_states(closes)
    ma20 = pd.Series(closes).rolling(MA_FAST, min_periods=MA_FAST).mean().values
    skew = np.where(np.isnan(ma20) | (ma20 == 0), 0.0, closes / ma20 - 1.0)
    return df["date_i"].values, np.asarray(states), skew


def mkt_attr_at(mkt_dates: np.ndarray, arr: np.ndarray, date_i: int):
    pos = int(np.searchsorted(mkt_dates, date_i, side="right")) - 1
    if pos < 0:
        return None
    return arr[pos]


def simulate_env(s: dict, code: str, name: str, events: list, *,
                 mkt_dates=None, mkt_states=None, mkt_skews=None,
                 stk_map: dict | None = None,
                 use_mkt: bool = False, use_stk: bool = False,
                 hold_up_tops: bool = False, stop_loss: float | None = None) -> dict:
    """底买顶卖 + 方向过滤 + 硬止损，T+1 次日开盘成交。

    events: [(成交bar, type)] 来自 events_backward（未过滤的全量信号）。
    决策日 = 成交bar-1（右K收盘那天），市场/个股状态取决策日收盘后可见值。
    方向1 禁买条件：市场状态=down 且 乖离率 <= -BEAR_SKEW（系统性急跌段）。
    个股状态优先用 stk_map（原始日K MA20 判态，date_i→state）；未提供时退回
    合并K线序列判态。
    止损：决策日（收盘）跌破止损线 → 次一 bar 开盘离场，与 T+1 语义一致。
    """
    n, d8, op, cl = s["n"], s["d8"], s["open"], s["close"]
    s0 = next((i for i in range(n) if d8[i] >= SIGNAL_START), None)
    if s0 is None or s0 + 1 >= n:
        return None

    stk_st = (_trend_states(cl) if stk_map is None
              and (use_stk or hold_up_tops) else None)

    def _mkt(dec_bar: int):
        if mkt_dates is None or dec_bar < 0:
            return "neutral", 0.0
        st = mkt_attr_at(mkt_dates, mkt_states, d8[dec_bar])
        sk = mkt_attr_at(mkt_dates, mkt_skews, d8[dec_bar])
        return (str(st) if st is not None else "neutral",
                float(sk) if sk is not None else 0.0)

    def _stk(dec_bar: int) -> str:
        if dec_bar < 0:
            return "neutral"
        if stk_map is not None:
            return stk_map.get(d8[dec_bar], "neutral")
        if stk_st is None:
            return "neutral"
        return stk_st[dec_bar]

    ev_by: dict[int, list] = {}
    for exe, typ in events:
        if s0 < exe < n:
            ev_by.setdefault(exe, []).append(typ)

    cash, shares, holding = 1.0, 0.0, False
    buy_bar, buy_px = -1, 0.0
    trades = []
    equity = np.ones(n)
    pend_stop = -1

    for t in range(s0 + 1, n):
        sold_now = False
        # ---------- 开盘执行 ----------
        # 1) 止损挂单（决策在昨日收盘，今日开盘即最可成交价）
        if t == pend_stop and holding and buy_px > 0:
            px = float(op[t])
            proceeds = shares * px * (1 - SELL_FEE)
            cost = shares * buy_px * (1 + BUY_FEE)
            cash, shares, holding = proceeds, 0.0, False
            trades.append({
                "code": code, "name": name,
                "buy_date": str(d8[buy_bar]), "sell_date": str(d8[t]),
                "buy_px": round(buy_px, 3), "sell_px": round(px, 3),
                "ret_pct": round((proceeds / cost - 1) * 100, 2),
                "days": max(1, t - buy_bar), "sell_reason": "止损",
            })
            buy_bar, buy_px, pend_stop, sold_now = -1, 0.0, -1, True

        # 2) 分型事件（止损当日不再重复交易）
        if t in ev_by and not sold_now:
            dec = t - 1
            for typ in ev_by[t]:
                if typ == "bottom" and not holding:
                    mst, msk = _mkt(dec)
                    if use_mkt and mst == "down" and msk <= -BEAR_SKEW:
                        continue
                    if use_stk and _stk(dec) == "down":
                        continue
                    px = float(op[t])
                    shares = cash / (px * (1 + BUY_FEE))
                    cash = 0.0
                    holding, buy_bar, buy_px = True, t, px
                    break
                elif typ == "top" and holding:
                    if hold_up_tops and _stk(dec) == "up":
                        continue
                    px = float(op[t])
                    proceeds = shares * px * (1 - SELL_FEE)
                    cost = shares * buy_px * (1 + BUY_FEE)
                    cash, shares, holding = proceeds, 0.0, False
                    trades.append({
                        "code": code, "name": name,
                        "buy_date": str(d8[buy_bar]), "sell_date": str(d8[t]),
                        "buy_px": round(buy_px, 3), "sell_px": round(px, 3),
                        "ret_pct": round((proceeds / cost - 1) * 100, 2),
                        "days": max(1, t - buy_bar), "sell_reason": "顶分型",
                    })
                    buy_bar, buy_px = -1, 0.0
                    break

        # ---------- 收盘估值 ----------
        equity[t] = cash + (shares * float(cl[t]) * (1 - SELL_FEE) if holding else 0.0)

        # ---------- 止损检查（决策日=今日收盘，执行=明日开盘） ----------
        if (holding and stop_loss is not None and buy_px > 0
                and float(cl[t]) <= buy_px * (1 - stop_loss) and t + 1 < n):
            pend_stop = t + 1

    equity[:s0 + 1] = 1.0

    # 买入持有基准
    px0 = float(op[s0])
    bh_ret = 0.0
    if px0 > 0 and float(cl[-1]) > 0:
        bh_end = (1 / (px0 * (1 + BUY_FEE))) * float(cl[-1]) * (1 - SELL_FEE)
        bh_ret = bh_end - 1

    strat_ret = float(equity[-1]) - 1.0
    curve = equity[s0:]
    peak = np.maximum.accumulate(curve)
    mdd = float((curve / peak - 1).min()) * 100 if len(curve) else 0.0

    wins = sum(1 for t_ in trades if t_["ret_pct"] > 0)
    return {
        "code": code, "name": name,
        "trades": trades,
        "n_trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1) if trades else None,
        "ret_pct": round(strat_ret * 100, 2),
        "bh_ret_pct": round(bh_ret * 100, 2),
        "excess_pct": round((strat_ret - bh_ret) * 100, 2),
        "max_dd_pct": round(mdd, 2),
        "end_holding": holding,
    }


def main() -> None:
    holdings = load_stock_holdings()
    log(f"持仓个股 {len(holdings)} 只: {[n for _, n in holdings]}")
    sdk_init(host="127.0.0.1", port=7899)

    mkt_dates, mkt_states, mkt_skews = load_mkt_states()
    log(f"沪深300 环境状态载入 {len(mkt_dates)} 根 | "
        f"最近60日状态分布: {dict(zip(*np.unique(mkt_states[-60:], return_counts=True)))}")

    codes = [c for c, _ in holdings]
    t0 = time.time()
    # stockdb 批量 get_data 对大代码列表间歇性丢标的，改为逐只取数 + 失败重试
    data: dict = {}
    for code in codes:
        for attempt in (1, 2):
            try:
                d1 = sdk_rd.get_data([code], start=FETCH_START, end=END,
                                     frequency="1d", fq="qfq")
                rows = d1.get(code) if isinstance(d1, dict) else None
                if rows:
                    data[code] = rows
                    break
            except Exception as e:
                log(f"{code} 第{attempt}次取数异常: {e}")
        if code not in data:
            log(f"{code} 取数失败（重试后仍无数据）")

    rows, all_tr = [], {"A0": [], "A1": [], "A2": [], "A3": []}
    for code, name in holdings:
        rdf = rows_to_df(data.get(code)) if data.get(code) else None
        if rdf is None:
            log(f"跳过 {code} {name}: 数据不足")
            continue
        tagged = build_merged(rdf)
        if tagged is None:
            log(f"跳过 {code} {name}: 无法构建合并K线")
            continue
        s = series_of(tagged)
        ev = events_backward(s)
        # 个股趋势状态用原始日K（标准 MA20）判态：date_i(YYYYMMDD) -> up/down/neutral
        _di = [to_int8(x) for x in rdf["datetime"].values]
        stk_map = dict(zip(_di, _trend_states(rdf["close"].astype(float).values)))
        r0 = simulate_env(s, code, name, ev)                                    # 基准
        r1 = simulate_env(s, code, name, ev, mkt_dates=mkt_dates,
                          mkt_states=mkt_states, mkt_skews=mkt_skews,
                          use_mkt=True)                                             # +市场环境
        r2 = simulate_env(s, code, name, ev, mkt_dates=mkt_dates,
                          mkt_states=mkt_states, mkt_skews=mkt_skews,
                          stk_map=stk_map, use_mkt=True, use_stk=True,
                          hold_up_tops=True)                                        # +个股趋势
        r3 = simulate_env(s, code, name, ev, mkt_dates=mkt_dates,
                          mkt_states=mkt_states, mkt_skews=mkt_skews,
                          stk_map=stk_map, use_mkt=True, use_stk=True,
                          hold_up_tops=True, stop_loss=STOP_LOSS)                   # +硬止损
        if not all([r0, r1, r2, r3]):
            log(f"跳过 {code} {name}: 起点不足")
            continue
        for tag, r in (("A0", r0), ("A1", r1), ("A2", r2), ("A3", r3)):
            all_tr[tag].extend(r["trades"])
        base = {"A0": r0, "A1": r1, "A2": r2, "A3": r3}
        row = {"name": name, "code": code, "bh": r0["bh_ret_pct"]}
        for tag, r in base.items():
            row[f"{tag}_n"] = r["n_trades"]
            row[f"{tag}_win"] = r["win_rate"]
            row[f"{tag}_ret"] = r["ret_pct"]
            row[f"{tag}_ex"] = r["excess_pct"]
            row[f"{tag}_mdd"] = r["max_dd_pct"]
        rows.append(row)
        log(f"{name} {code}: A0={r0['ret_pct']:+.1f}%({r0['n_trades']}笔) "
            f"A1={r1['ret_pct']:+.1f}%({r1['n_trades']}笔) "
            f"A2={r2['ret_pct']:+.1f}%({r2['n_trades']}笔) "
            f"A3={r3['ret_pct']:+.1f}%({r3['n_trades']}笔) "
            f"BH={r0['bh_ret_pct']:+.1f}%")

    if not rows:
        log("无任何有效标的")
        return
    df_rows = pd.DataFrame(rows)
    tags = ("A0", "A1", "A2", "A3")
    detail = {"BH_avg": float(df_rows["bh"].mean())}
    for tag in tags:
        detail[f"{tag}_avg"] = float(df_rows[f"{tag}_ret"].mean())
        detail[f"{tag}_beat"] = int((df_rows[f"{tag}_ex"] > 0).sum())
        detail[f"{tag}_n_sum"] = int(df_rows[f"{tag}_n"].sum())
    detail["A3_vs_A0"] = detail["A3_avg"] - detail["A0_avg"]
    detail["A1_vs_A0"] = detail["A1_avg"] - detail["A0_avg"]
    detail["A2_vs_A1"] = detail["A2_avg"] - detail["A1_avg"]

    out_dir = os.path.join(ROOT, "output", "backtest",
                           f"holdings_env_{datetime.now():%Y%m%d}")
    os.makedirs(out_dir, exist_ok=True)
    for tag in tags:
        pd.DataFrame(all_tr[tag]).to_csv(os.path.join(out_dir, f"trades_{tag}.csv"),
                                         index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"stocks": len(rows), **detail}, f, ensure_ascii=False, indent=2)

    # ---------- 控制台汇总 ----------
    print("\n=== 组合汇总（等权平均，含费、T+1 次日开盘）===")
    print(f"A0 基准(后向窗口)        平均 {detail['A0_avg']:+.2f}% ｜ "
          f"跑赢BH {detail['A0_beat']}/{len(rows)} ｜ {detail['A0_n_sum']}笔")
    print(f"A1 +市场环境(下行&乖离≤-{BEAR_SKEW*100:.0f}%急跌禁买) 平均 {detail['A1_avg']:+.2f}% ｜ "
          f"跑赢BH {detail['A1_beat']}/{len(rows)} ｜ {detail['A1_n_sum']}笔 ｜ Δ={detail['A1_vs_A0']:+.2f}pp")
    print(f"A2 +个股趋势(空头禁买/多头顶不清) 平均 {detail['A2_avg']:+.2f}% ｜ "
          f"跑赢BH {detail['A2_beat']}/{len(rows)} ｜ {detail['A2_n_sum']}笔 ｜ Δ={detail['A2_vs_A1']:+.2f}pp")
    print(f"A3 +硬止损10%             平均 {detail['A3_avg']:+.2f}% ｜ "
          f"跑赢BH {detail['A3_beat']}/{len(rows)} ｜ {detail['A3_n_sum']}笔 ｜ Δ={detail['A3_vs_A0']:+.2f}pp")
    print(f"买入持有                  平均 {detail['BH_avg']:+.2f}%")
    pd.set_option("display.unicode.east_asian_width", True)
    pd.set_option("display.width", 340)
    pd.set_option("display.max_columns", None)
    show = df_rows[["name", "code", "bh"] + [f"{t}_{c}" for t in tags
                                             for c in ("ret", "n", "win", "ex", "mdd")]]
    print("\n" + show.to_string(index=False))
    print(f"\n完成：{out_dir}（不生成 HTML，CSV + summary.json 已落盘，耗时 {time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
