"""缠论项目 · 计算核心 runner（Phase 4 · Step 4-1）。

抽出两个可组合函数，供 web 侧（Phase 5）与 CLI（Phase 6）复用：
  - fetch_data(...): 按市场类型分派，调用对应 fetcher 取数；
  - analyze(...):    执行缠论分析（ChanlunProcessor.process_klines + summary）。

设计约束（对齐《分步执行清单》Step 4-1，用户已确认）：
  1. 入参与执行顺序与原 web 侧 analyze_stock_with_mootdx/baostock 完全一致；
  2. @st.cache_data 缓存不引入 runner，留在 web 侧；
  3. CLI 的 input() 交互循环、图表保存/展示逻辑不放入 runner；
  4. 可视化（plotly_chanlun_visualization）由调用方按需引入 src.visual.plotly_viz，
     runner 保持纯计算，与原 web 侧"分析后单独绘图"的执行顺序一致；
  5. v4 唯一数据源 Tushare：fetch_data 按 market_type 分派到
     stock→daily / etf→fund_daily / index→index_daily（TushareClient.fetch_daily_data）；
  6. analyze() 走保守契约返回 (result_df, summary)，同时把分型/笔 list 塞进
     summary dict（复用 processor 已存的中间态，不重复计算），
     验证脚本无需重复实例化 ChanlunProcessor。
"""
from __future__ import annotations

import pandas as pd

from src.core.chanlun_processor import ChanlunProcessor
from src.data.tushare_fetcher import TushareClient
from src.utils.common import get_market_type


def fetch_data(
    code: str,
    start_date: str,
    end_date: str,
    market_type: str | None = None,
    data_type: str = "daily",
    frequency: str = "30",
    data_source: str = "tushare",
) -> pd.DataFrame:
    """获取 K 线数据：按数据源分派（tushare / baostock）。

    入参与原 web 侧 analyze_stock_with_mootdx/baostock 一致：
    (stock_code, start_date, end_date, data_type, frequency)。

    Args:
        code: 标准化代码（Tushare 格式 600000.SH / 510300.SH / 000300.SH，
            或 Baostock 格式 sh.600588 / sz.000001）
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        market_type: stock/etf/index/hk；缺省时由 get_market_type(code) 自动识别
            （仅 Tushare 源生效，Baostock 不区分市场类型）
        data_type: daily / minute
        frequency: 日线 'd'，分钟线 5/15/30/60（仅 Baostock 源走分钟线；
            Tushare 源当前仅支持 daily）
        data_source: 'tushare'（默认，需 TUSHARE_TOKEN）或 'baostock'（免费免 token）

    Returns:
        标准 8 列 DataFrame：datetime,open,high,low,close,volume,amount,code
    """
    if data_source == "baostock":
        return _fetch_from_baostock(code, start_date, end_date, data_type, frequency)

    # 默认 tushare 源
    if data_type != "daily":
        raise ValueError(
            f"Tushare 数据源当前仅支持 daily（收到 data_type={data_type!r}），分钟线请改用 Baostock 源"
        )
    if market_type is None:
        market_type = get_market_type(code)
    if market_type == "hk":
        raise ValueError("Tushare 不支持港股（需单独权限），请使用 A股/ETF/指数或 Baostock 源")

    client = TushareClient()
    if not client.is_available():
        print("✗ 错误：未配置 TUSHARE_TOKEN，无法获取行情数据")
        print("  请在 .env 中设置 TUSHARE_TOKEN=你的token，或切换数据源为 Baostock")
        sys.exit(2)
    return client.fetch_daily_data(code, start_date, end_date, market_type)


def _fetch_from_baostock(
    code: str,
    start_date: str,
    end_date: str,
    data_type: str,
    frequency: str,
) -> pd.DataFrame:
    """从 Baostock 数据源取数（免费、免 token，支持 A股/ETF/指数日线与分钟线）。"""
    from src.data.baostock_fetcher import BaostockClient

    bs_freq = "d" if data_type == "daily" else str(frequency)
    try:
        client = BaostockClient()
        return client.fetch_daily_data(
            code,
            start_date,
            end_date,
            frequency=bs_freq,
            adjustflag="2",
        )
    except ImportError:
        raise RuntimeError(
            "未安装 baostock，请执行: pip install baostock"
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
            # 兼容 Tushare(20250307) 与 Baostock(2025-03-07) 两种日期格式：
            # 去除所有非数字字符后转 int，归一为纯日期整数字符串
            dt_raw = str(row["datetime"]).replace("-", "").replace("/", "")
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
            )
    return segments
