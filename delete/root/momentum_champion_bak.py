# -*- coding: utf-8 -*-
"""
momentum_champion.py - 独立脚本：用 Baostock 查询四个 ETF 的日 K 线，计算动量冠军。

特点：
- 不依赖本项目任何模块（不 import config / src），可单独拷走运行。
- 动量分数口径（移植自项目 src/strategy.py 的 _compute_single_momentum_score）：
      对最近 N 个交易日的收盘价取对数 y = ln(close)，用 x = 0..N-1 做一元线性回归，
      年化收益率 = exp(回归斜率)^250 - 1，R² = 回归拟合优度，
      动量分数 = 年化收益率 × R²。
  分数最高者为动量冠军（与项目投顾流水的“动量分”完全一致）。
- 自动处理周末/节假日：end_date 默认取“系统昨天”，Baostock 只返回交易日，
  实际使用的「最近交易日」会在结果中打印；无需手动判断交易日。

依赖：pip install baostock pandas numpy

用法：
    python momentum_champion.py                 # 默认：昨天收盘，25 日动量（对齐 REGRESSION_DAYS）
    python momentum_champion.py --lookback 60   # 改成 60 日动量
    python momentum_champion.py --date 2026-07-22
"""

import argparse
import math
from datetime import datetime, timedelta

import baostock as bs
import numpy as np
import pandas as pd

# 待比较的四个 ETF（带后缀代码 -> 名称，仅用于展示）
ETF_LIST = {
    '510180.SH': '上证180ETF',
    '159915.SZ': '创业板ETF',
    '513100.SH': '纳指ETF',
    '518880.SH': '黄金ETF',
}

# 年化交易日数（与项目 src/strategy.py 一致）
TRADING_DAYS_PER_YEAR = 250


def to_bs_code(ts_code):
    """510180.SH -> sh.510180；159915.SZ -> sz.159915"""
    code, market = ts_code.split('.')
    prefix = 'sh' if market == 'SH' else 'sz'
    return f'{prefix}.{code}'


def fetch_kline(ts_code, end_date, window_days=180):
    """拉取 ts_code 截至 end_date 的日 K 线（前复权），返回按日期升序的 DataFrame。

    window_days：往回多取多少自然日，确保覆盖 lookback 所需的交易日数量。
    """
    bs_code = to_bs_code(ts_code)
    start_date = (datetime.strptime(end_date, '%Y-%m-%d')
                  - timedelta(days=window_days)).strftime('%Y-%m-%d')
    rs = bs.query_history_k_data_plus(
        bs_code,
        'date,open,high,low,close,volume',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2',  # 前复权，保证价格连续
    )
    if rs.error_code != '0':
        raise RuntimeError(f'Baostock 查询失败 {ts_code}: code={rs.error_code} msg={rs.error_msg}')
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    df = pd.DataFrame(rows, columns=rs.fields)
    df['date'] = pd.to_datetime(df['date'])
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('date').reset_index(drop=True)


def _momentum_score(close_window):
    """动量分数 = 年化收益率 × R²（项目 src/strategy.py 口径，对 log 价格线性回归）。

    Args:
        close_window: 长度为 lookback 的收盘价序列（ndarray / list），需全为正。
    Returns:
        (momentum_score, annualized_return, r_squared)
    """
    y = np.log(np.asarray(close_window, dtype=float))
    x = np.arange(y.size)
    slope, intercept = np.polyfit(x, y, 1)
    annualized = math.pow(math.exp(slope), TRADING_DAYS_PER_YEAR) - 1
    ss_res = np.sum((y - (slope * x + intercept)) ** 2)
    r_squared = 1.0 - ss_res / ((len(y) - 1) * np.var(y, ddof=1))
    return annualized * r_squared, annualized, r_squared


def calc_momentum(df, lookback=25):
    """计算动量分数。返回 dict 或 None（数据不足时）。"""
    closes = df['close'].dropna().values
    if len(closes) < lookback + 1:
        return None
    # 最近 lookback 个交易日，但不含最后一天：
    # 对齐项目 src/strategy.py 的 iloc[idx-rd: idx]（用信号日前 N 天算动量，不含当日）
    window = closes[-(lookback + 1):-1]
    if window.min() <= 0:
        return None
    score, annualized, r_squared = _momentum_score(window)
    return {
        'last_date': df['date'].iloc[-1].strftime('%Y-%m-%d'),
        'last_close': float(closes[-1]),
        'base_close': float(window[0]),
        'total_return': float(closes[-1] / window[0] - 1.0),  # 区间累计收益，参考用
        'annualized': float(annualized),
        'r_squared': float(r_squared),
        'momentum_score': float(score),
    }


def main():
    parser = argparse.ArgumentParser(description='四个 ETF 动量冠军计算（Baostock）')
    parser.add_argument('--date', type=str, default=None,
                        help='终点日期 YYYY-MM-DD，默认=昨天')
    parser.add_argument('--lookback', type=int, default=25,
                        help='动量回归窗口（交易日数），默认 25（对齐项目 REGRESSION_DAYS）')
    parser.add_argument('--window', type=int, default=180,
                        help='往回拉取的自然日数，默认 180（确保覆盖窗口）')
    args = parser.parse_args()

    end_date = args.date or (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f'Baostock 登录失败: {lg.error_msg}')
    try:
        results = []
        for ts_code, name in ETF_LIST.items():
            try:
                df = fetch_kline(ts_code, end_date, window_days=args.window)
                mom = calc_momentum(df, lookback=args.lookback)
            except Exception as e:
                print(f'[跳过] {name}({ts_code}): {e}')
                continue
            if mom is None:
                print(f'[跳过] {name}({ts_code}): 交易日数据不足 {args.lookback} 根')
                continue
            results.append({
                'etf_code': ts_code,
                'etf_name': name,
                **mom,
            })

        if not results:
            print('无可用数据，退出。')
            return

        # 按动量分数（年化收益 × R²）降序排名
        results.sort(key=lambda r: r['momentum_score'], reverse=True)
        for i, r in enumerate(results, 1):
            r['rank'] = i

        print(f'\n=== 动量冠军（终点 {end_date}，窗口 {args.lookback} 交易日）===')
        print(f'{"排名":<4}{"代码":<12}{"名称":<12}{"最近交易日":<12}'
              f'{"收盘价":>10}{"动量分":>12}{"R2":>10}{"年化":>12}')
        for r in results:
            print(f'{r["rank"]:<4}{r["etf_code"]:<12}{r["etf_name"]:<12}'
                  f'{r["last_date"]:<12}{r["last_close"]:>10.3f}'
                  f'{r["momentum_score"]:>12.4f}{r["r_squared"]:>10.3f}'
                  f'{r["annualized"] * 100:>11.2f}%')

        champ = results[0]
        print(f'\n>>> 动量冠军：{champ["etf_name"]}({champ["etf_code"]}) '
              f'动量分 {champ["momentum_score"]:.4f}'
              f'（{champ["last_date"]} 收盘，R2={champ["r_squared"]:.3f}，'
              f'年化 {champ["annualized"] * 100:.2f}%）')
    finally:
        bs.logout()


if __name__ == '__main__':
    main()
