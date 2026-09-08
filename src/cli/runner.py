"""缠论项目 · 计算核心 runner（Phase 4 · Step 4-1）。

抽出两个可组合函数，供 web 侧（Phase 5）与 CLI（Phase 6）复用：
  - fetch_data(...): 按市场类型分派，调用对应 fetcher 取数；
  - analyze(...):    执行缠论分析（ChanlunProcessor.process_klines + summary）。

设计约束（对齐《分步执行清单》Step 4-1，用户已确认）：
  1. 入参与执行顺序与原 web 侧 analyze_stock 一致；
  2. @st.cache_data 缓存不引入 runner，留在 web 侧；
  3. CLI 的 input() 交互循环、图表保存/展示逻辑不放入 runner；
  4. 可视化（plotly_chanlun_visualization）由调用方按需引入 src.visual.plotly_viz，
     runner 保持纯计算，与原 web 侧"分析后单独绘图"的执行顺序一致；
  5. 唯一数据源 StockDB：fetch_data 统一走 StockDBFetcher 取数；
  6. analyze() 走保守契约返回 (result_df, summary)，同时把分型/笔 list 塞进
     summary dict（复用 processor 已存的中间态，不重复计算），
     验证脚本无需重复实例化 ChanlunProcessor。
"""
from __future__ import annotations

import sys

import pandas as pd

from src.core.chanlun_processor import ChanlunProcessor
from src.utils.common import get_market_type

# 最近一次取数来源标记（唯一数据源：本地 stockdb 服务），
# 供 web 侧提示用户数据来源。
last_data_source: str | None = None


def fetch_data(
    code: str,
    start_date: str,
    end_date: str,
    market_type: str | None = None,
    data_type: str = "daily",
    frequency: str = "30",
    data_source: str = "stockdb",
) -> pd.DataFrame:
    """获取 K 线数据（唯一数据源：本地 stockdb 服务）。

    入参与原 web 侧 analyze_stock 一致：
    (stock_code, start_date, end_date, data_type, frequency)。

    Args:
        code: 标准化代码（600000.SH / 510300.SH / 000300.SH）
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        market_type: stock/etf/index；保留参数以兼容既有调用方，
            实际由 _fetch_from_stockdb 内部调用 get_market_type(code) 自动识别
        data_type: daily / minute
        frequency: 日线 'daily'，分钟线 5/15/30/60
        data_source: 保留参数以兼容既有调用方，当前唯一有效值为 'stockdb'

    Returns:
        标准 8 列 DataFrame：datetime,open,high,low,close,volume,amount,code
    """
    df = _fetch_from_stockdb(code, start_date, end_date, data_type, frequency)
    globals()["last_data_source"] = "stockdb"
    return df


def _fetch_from_stockdb(
    code: str,
    start_date: str,
    end_date: str,
    data_type: str,
    frequency: str,
) -> pd.DataFrame:
    """从本地 StockDB 数据源取数（免 token、全本地、低延迟）。

    stockdb 经 D:\\stockdb\\stockdb.exe 本地服务 + stock_sdk 访问，数据全本地。
    日线与分钟线均走 rd.get_data（支持 qfq/hfq 复权、分钟聚合 1m/5m/15m/30m/60m）。

    注意：stockdb 取数暂未接入 kline_cache 写回（本地库本身即为持久缓存），
    后续若需统一缓存层可在此包裹 kline_cache.load_or_fetch。
    """
    from src.data.stockdb_fetcher import StockDBFetcher
    from src.utils.logger import log

    log("RUNNER", "INFO",
        f"进入 StockDB 取数分支 [{code}] {start_date}~{end_date} type={data_type} freq={frequency}",
        code=code, start=start_date, end=end_date)
    try:
        client = StockDBFetcher()
        if not client.is_available():
            raise RuntimeError(
                "StockDB 不可用：请确认 D:\\stockdb\\stockdb.exe 已启动且 SDK 路径正确"
            )
        df = client.fetch_daily_data(
            code, start_date, end_date,
            market_type=get_market_type(code),
            adj="qfq",
            frequency=frequency if data_type == "minute" else "daily",
        )
        log("RUNNER", "INFO",
            f"取数完成：{len(df)} 条（来源 stockdb）",
            code=code, rows=len(df), source="stockdb")
        return df
    except ImportError as e:
        raise RuntimeError(
            f"无法导入 stock_sdk：请确认 STOCKDB_SDK_PATH 指向包含 stockdb.pyd / stock_sdk.py 的目录（{e}）"
        )


def analyze(data: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """执行缠论分析。

    Args:
        data: 标准 8 列 DataFrame（fetch_data 的返回）

    Returns:
        (result_df, summary)
        - result_df: process_klines 返回的带分型/笔标记的 DataFrame
        - summary: get_processing_summary() 的汇总 dict，额外注入两个键：
            'fractals': list[{index,type,high,low,datetime}]  复用 processor.fractals_data
            'segments': list[{start_idx,end_idx,start_type,end_type,direction,
                              start_price,end_price}]        复用 processor.segments
          （均为复用 processor 已存中间态的再组织，不重复计算）
    """
    processor = ChanlunProcessor()
    result_df = processor.process_klines(data)
    summary = processor.get_processing_summary()
    summary["fractals"] = _extract_fractals(processor)
    summary["segments"] = _extract_segments(processor)
    return result_df, summary


def _extract_fractals(processor: ChanlunProcessor) -> list[dict]:
    """从 processor.fractals_data 提取最终分型 list（与黄金样本 expected.json 同构）。

    注意：黄金样本约定 datetime 为纯日期整数字符串（如 "20240118"）。
    fractals_data 的 datetime 列经 merge_klines 构造 DataFrame 后可能被推断为
    float（"20240118.0"），此处统一归一到 int 再 str，保证与 expected.json 逐字一致。
    """
    fractals = []
    if processor.fractals_data is not None:
        is_f = processor.fractals_data[processor.fractals_data["is_fractal"]]
        for idx, row in is_f.iterrows():
            # 统一日期格式（日线 2026-07-13 / 20260713 → 20260713）：
            # 归一为纯数字字符串（日线 2026-07-13 → 20260713；
            # 分钟线 2026-07-13 14:00:00 → 20260713140000），再转 int
            dt_raw = (
                str(row["datetime"])
                .replace("-", "")
                .replace("/", "")
                .replace(" ", "")
                .replace(":", "")
            )
            fractals.append(
                {
                    "index": int(idx),
                    "type": str(row["fractal_type"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "datetime": str(int(dt_raw)),
                }
            )
    return fractals


def _extract_segments(processor: ChanlunProcessor) -> list[dict]:
    """从 processor.segments 提取笔 list（与黄金样本 expected.json 同构）。"""
    segments = []
    if hasattr(processor, "segments") and processor.segments:
        for seg in processor.segments:
            segments.append(
                {
                    "start_idx": int(seg["start_idx"]),
                    "end_idx": int(seg["end_idx"]),
                    "start_type": str(seg["start_type"]),
                    "end_type": str(seg["end_type"]),
                    "direction": str(seg["direction"]),
                    "start_price": float(seg["start_price"]),
                    "end_price": float(seg["end_price"]),
                }
            )  # 注意：必须同时注入 start_price/end_price（笔端点价格），
               # 否则下游（如 AI 研判 payload）需自行反查，易出错。
    return segments
