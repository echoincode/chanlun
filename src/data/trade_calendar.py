"""交易日历（本地缓存 + stockdb 增量补齐）。

维护一份 A股交易日历（cache/trade_dates.csv）：
  - 本地有就直接读，不发起网络请求；
  - 本地缺失或请求日期超出本地覆盖范围时，通过 stockdb.get_trade_days
    增量补齐缺失段并写回本地；
  - stockdb 不可用 / 拉取失败时记录告警，由 is_trading_day 的 weekday 兜底。

对外提供：
  - ensure_trade_calendar(end_date=None)：确保本地日历覆盖到 end_date（增量补齐）
  - is_trading_day(date_str)：查询某天是否为交易日（本地优先，必要时兜底 weekday）
  - get_last_trading_day(date_str=None)：返回 date_str 之前（含当天）最近的交易日
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd

from src.utils.logger import log

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cache",
)
_CACHE_FILE = os.path.join(_CACHE_DIR, "trade_dates.csv")

# 本地日历表起始下界（A股历史数据足够覆盖）
_CAL_START = "2015-01-01"

# 进程内缓存，避免同一进程多次读盘
_cache_df: pd.DataFrame | None = None


def _load_local() -> pd.DataFrame:
    """读取本地交易日历；不存在返回空 DataFrame（columns 固定）。"""
    global _cache_df
    if _cache_df is not None:
        return _cache_df
    if os.path.exists(_CACHE_FILE):
        try:
            _cache_df = pd.read_csv(_CACHE_FILE, dtype={"date": str, "is_trading_day": int})
            return _cache_df
        except Exception:
            _cache_df = pd.DataFrame(columns=["date", "is_trading_day"])
            return _cache_df
    _cache_df = pd.DataFrame(columns=["date", "is_trading_day"])
    return _cache_df


def _save_local(df: pd.DataFrame) -> None:
    """写回本地日历（按 date 去重）。"""
    global _cache_df
    os.makedirs(_CACHE_DIR, exist_ok=True)
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    df.to_csv(_CACHE_FILE, index=False)
    _cache_df = df


def _ensure_stockdb_ready() -> None:
    """确保 stockdb SDK 已 init（复用 stockdb_fetcher 的连接单例，幂等）。"""
    from src.data.stockdb_fetcher import StockDBFetcher

    host = os.environ.get("STOCKDB_HOST", "127.0.0.1")
    port = int(os.environ.get("STOCKDB_PORT", "7899"))
    # _get_rdk 内部已完成 init；此处只触发副作用
    StockDBFetcher._get_rdk(host, port)


def _fetch_from_stockdb(start: str, end: str) -> pd.DataFrame:
    """通过 stockdb.get_trade_days 拉取 [start, end] 区间交易日。

    返回 columns=[date, is_trading_day] 的 DataFrame；
    失败时抛出异常，由 ensure_trade_calendar 捕获并回退。
    """
    _ensure_stockdb_ready()
    from stock_sdk import get_trade_days

    dates = get_trade_days(start_date=start, end_date=end)
    if not dates:
        return pd.DataFrame(columns=["date", "is_trading_day"])
    df = pd.DataFrame({"date": [str(d)[:10] for d in dates]})
    df["is_trading_day"] = 1
    return df


def ensure_trade_calendar(end_date: str | None = None) -> pd.DataFrame:
    """确保本地交易日历覆盖到 end_date（默认今天）。

    策略：
      - 本地已覆盖 end_date → 直接返回；
      - 本地缺失或超出覆盖范围 → 调 stockdb.get_trade_days 增量补齐并写回；
      - stockdb 不可用 / 拉取失败 → 记录告警并返回已有本地数据，
        由 is_trading_day 的 weekday 兜底。
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    local = _load_local()
    if not local.empty:
        local_max = str(local["date"].max())
        if local_max >= end_date:
            return local  # 已覆盖，直接返回
        fetch_start = (
            datetime.strptime(local_max, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        log("TRADE_CAL", "INFO",
            f"本地交易日历已覆盖至 {local_max}，增量补齐 {fetch_start}~{end_date}",
            fetch_start=fetch_start, end=end_date)
    else:
        fetch_start = _CAL_START
        log("TRADE_CAL", "INFO",
            f"本地交易日历为空，首次全量拉取 {fetch_start}~{end_date}",
            fetch_start=fetch_start, end=end_date)

    try:
        fresh = _fetch_from_stockdb(fetch_start, end_date)
    except Exception as e:
        log("TRADE_CAL", "WARNING",
            f"stockdb 交易日历拉取失败，兜底本地（可能为空）: {e}")
        return local

    if fresh.empty:
        return local
    merged = pd.concat([local, fresh], ignore_index=True)
    _save_local(merged)
    log("TRADE_CAL", "INFO",
        f"交易日历补齐完成，新增 {len(fresh)} 条，本地共 {len(merged)} 条")
    return merged


def is_trading_day(date_str: str) -> bool:
    """查询某天是否为交易日（本地优先；本地缺失或拉取失败时兜底 weekday）。

    Args:
        date_str: YYYY-MM-DD
    Returns:
        True 表示交易日
    """
    # 兜底：非法日期直接按 weekday 判断
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False

    local = ensure_trade_calendar(date_str)
    hit = local[local["date"] == date_str]
    if not hit.empty:
        _is_td = int(hit.iloc[0]["is_trading_day"]) == 1
        log("TRADE_CAL", "DEBUG",
            f"is_trading_day({date_str})={_is_td}（本地命中）")
        return _is_td

    # 本地无该日期（拉取失败等情况）：兜底到 weekday 判断
    _fallback = datetime.strptime(date_str, "%Y-%m-%d").weekday() < 5
    log("TRADE_CAL", "WARNING",
        f"is_trading_day({date_str}) 本地缺失，兜底 weekday={_fallback}")
    return _fallback


def get_last_trading_day(date_str: str | None = None) -> str:
    """返回 date_str 之前（含当天）最近的交易日，YYYY-MM-DD。"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    d = datetime.strptime(date_str, "%Y-%m-%d")
    # 最多往前找 30 天（覆盖春节等长假期）
    for _ in range(30):
        if is_trading_day(d.strftime("%Y-%m-%d")):
            return d.strftime("%Y-%m-%d")
        d -= timedelta(days=1)
    # 兜底：找不到则返回原日期（理论上不会走到）
    return date_str
