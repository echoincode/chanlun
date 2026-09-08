"""缠论项目 · 数据层（Phase 3）。

承载 BaseFetcher 抽象基类与各数据源 fetcher 实现。
数据源统一为本地 stockdb 服务，原 tushare / baostock / mootdx 实现已移除。
"""
from src.data.base_fetcher import BaseFetcher

__all__ = ["BaseFetcher"]
