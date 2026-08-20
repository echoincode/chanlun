"""缠论项目 · 数据源抽象基类（Phase 3 · Step 3-1）。

规定统一的数据获取接口，所有 fetcher 子类实现。
返回标准 DataFrame：列 datetime,open,high,low,close,volume,amount,code
（datetime 为 YYYY-MM-DD 字符串，volume 单位为股，amount 单位为元）。

v4 决策：数据源统一为 Tushare，原 baostock/mootdx 已弃用，BaseFetcher 仅由
TushareClient 实现。抽象基类保留通用接口，便于未来扩展其他数据源。
"""
from abc import ABC, abstractmethod

import pandas as pd


class BaseFetcher(ABC):
    """数据源抽象基类。

    子类必须实现 fetch_daily_data，返回标准 8 列 DataFrame：
    datetime,open,high,low,close,volume,amount,code
    """

    @abstractmethod
    def fetch_daily_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        market_type: str = "stock",
    ) -> pd.DataFrame:
        """获取日线数据，返回标准 8 列 DataFrame。

        Args:
            code: 标准化代码（Tushare 风格 600000.SH / 000001.SZ / 510300.SH / 00700.HK）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            market_type: 市场类型 stock/etf/index/hk

        Returns:
            DataFrame，列：datetime,open,high,low,close,volume,amount,code
        """
        raise NotImplementedError
