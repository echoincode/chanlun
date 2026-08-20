"""缠论项目 · 数据源抽象基类（Phase 3 · Step 3-1）。

规定统一的数据获取接口，所有 fetcher 子类实现。
返回标准 DataFrame：列 datetime,open,high,low,close,volume,amount,code
（datetime 为 YYYY-MM-DD 字符串，volume 单位为股，amount 单位为元）。
"""
from abc import ABC, abstractmethod

import pandas as pd


class BaseFetcher(ABC):
    """数据源抽象基类。

    子类必须实现 fetch_daily_data，返回标准 8 列 DataFrame：
    datetime,open,high,low,close,volume,amount,code
    """

    def is_available(self) -> bool:
        """数据源是否已配置可用（如 token 是否就绪）。

        默认返回 True（免 token 源如 Baostock）。需要 token 的子类应覆盖。
        """
        return True

    @abstractmethod
    def fetch_daily_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        market_type: str = "stock",
        adj: str = "qfq",
    ) -> pd.DataFrame:
        """获取日线数据，返回标准 8 列 DataFrame。

        Args:
            code: 标准化代码（Tushare 风格 600000.SH / 000001.SZ / 510300.SH / 00700.HK，
                或 Baostock 风格 sh.600588）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            market_type: 市场类型 stock/etf/index/hk
            adj: 复权方式（None 未复权 / "qfq" 前复权 / "hfq" 后复权），
                免 token 源可忽略

        Returns:
            DataFrame，列：datetime,open,high,low,close,volume,amount,code
        """
        raise NotImplementedError
