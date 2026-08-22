"""K 线本地缓存（方案 1：CSV per 标的）。

设计（尽量简单）：
  - 按标的代码存盘：cache/{code}.csv，列为标准 8 列
    datetime,open,high,low,close,volume,amount,code
  - 查询时先判断请求区间 [start, end] 是否已被缓存覆盖：
      缓存区间 [cached_min, cached_max] ⊇ [start, end] → 直接切片返回，不查 Baostock
    否则查询缺失部分（左段 / 右段），合并去重后写回 CSV
  - 增量补齐：避免每次都全量重查，Baostock 第一次通常拉全量，之后区间命中

约定：
  - datetime 为 YYYY-MM-DD 字符串，可直接按字典序比较（对齐 Baostock 返回格式）
  - 文件名中的 '.' 替换为 '_'，避免路径分隔歧义
"""
from __future__ import annotations

import os

import pandas as pd

# 缓存根目录（已在 .gitignore 忽略）
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache")

# 标准列顺序
_COLUMNS = ["datetime", "open", "high", "low", "close", "volume", "amount", "code"]

# 最近一次取数来源标记（"local" 表示命中本地缓存；"remote" 表示查询了 Baostock）。
# 供上层 UI 提示用户数据来源，仅作展示用途。
last_source: str | None = None


def _safe_name(code: str) -> str:
    """将标的代码转为安全文件名（去掉路径分隔字符）。"""
    return code.replace(".", "_").replace("/", "_").replace("\\", "_")


def _cache_path(code: str) -> str:
    return os.path.join(CACHE_DIR, f"{_safe_name(code)}.csv")


def _load(code: str) -> pd.DataFrame | None:
    """读取缓存 CSV；不存在或为空返回 None。"""
    path = _cache_path(code)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, dtype={"datetime": str})
        if df.empty:
            return None
        # 保障列顺序与类型
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["datetime"] = df["datetime"].astype(str)
        return df
    except Exception:
        # 任何读取异常都视为无缓存，交由后端重新拉取
        return None


def _save(code: str, df: pd.DataFrame) -> None:
    """写出缓存 CSV（按 datetime 升序去重）。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    df = df.copy()
    df["datetime"] = df["datetime"].astype(str)
    df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    df = df[[c for c in _COLUMNS if c in df.columns]]
    df.to_csv(_cache_path(code), index=False)


def load_or_fetch(
    code: str,
    start_date: str,
    end_date: str,
    fetcher,
    data_type: str = "daily",
    frequency: str = "30",
    adjustflag: str = "2",
) -> pd.DataFrame:
    """带本地缓存的取数。

    Args:
        code: 标的代码（作为缓存文件名）
        start_date / end_date: 请求区间 YYYY-MM-DD
        fetcher: 真实取数后端（BaostockClient 实例），需有
                 fetch_daily_data(code, start_date, end_date, frequency, adjustflag)
        data_type / frequency / adjustflag: 透传给 fetcher

    Returns:
        标准 8 列 DataFrame（切片自缓存或后端返回）
    """
    cached = _load(code)

    # 无缓存：直接全量查询并保存
    if cached is None:
        globals()["last_source"] = "remote"
        fresh = fetcher.fetch_daily_data(
            code, start_date, end_date, frequency=frequency, adjustflag=adjustflag
        )
        if not fresh.empty:
            _save(code, fresh)
        return fresh

    cached_min = str(cached["datetime"].min())
    cached_max = str(cached["datetime"].max())

    # 完全命中：请求区间被缓存覆盖
    if cached_min <= start_date and cached_max >= end_date:
        globals()["last_source"] = "local"
        mask = (cached["datetime"] >= start_date) & (cached["datetime"] <= end_date)
        return cached[mask].reset_index(drop=True)

    # 部分缺失：补齐左段 / 右段
    globals()["last_source"] = "remote"
    to_fetch = []
    if start_date < cached_min:
        to_fetch.append((start_date, _prev_day(cached_min)))
    if end_date > cached_max:
        to_fetch.append((_next_day(cached_max), end_date))

    for seg_start, seg_end in to_fetch:
        if seg_start > seg_end:
            continue
        fresh = fetcher.fetch_daily_data(
            code, seg_start, seg_end, frequency=frequency, adjustflag=adjustflag
        )
        if not fresh.empty:
            cached = pd.concat([cached, fresh], ignore_index=True)

    # 写回合并后的全量缓存
    _save(code, cached)

    mask = (cached["datetime"] >= start_date) & (cached["datetime"] <= end_date)
    return cached[mask].reset_index(drop=True)


def _prev_day(date_str: str) -> str:
    from datetime import datetime, timedelta

    d = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _next_day(date_str: str) -> str:
    from datetime import datetime, timedelta

    d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    return d.strftime("%Y-%m-%d")
