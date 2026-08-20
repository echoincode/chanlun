"""缠论项目 · 数据层（Phase 3）。

承载 BaseFetcher 抽象基类与各数据源 fetcher 实现。
v4：数据源统一为 Tushare，原 baostock/mootdx 已弃用。
"""
from src.data.base_fetcher import BaseFetcher

__all__ = ["BaseFetcher"]
