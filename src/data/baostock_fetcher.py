"""Baostock 数据源 fetcher（新增 baostock 源，与 TushareClient 并列）。

实现 BaseFetcher.fetch_daily_data 统一接口，返回标准 8 列 DataFrame：
datetime,open,high,low,close,volume,amount,code
（datetime 为 YYYY-MM-DD 字符串，volume 单位为股，amount 单位为元）。

代码格式：Baostock 使用 sh.600588 / sz.000001 风格，本 fetcher 内部做双向转换，
对外接受 Tushare 风格（600588.SH）与 Baostock 风格（sh.600588）两种输入。

Baostock 免费、无需 token，支持 A股/ETF/指数日线与分钟线。
"""
from __future__ import annotations

import warnings
from typing import Optional

import pandas as pd

from src.data.base_fetcher import BaseFetcher

warnings.filterwarnings("ignore")


def _tushare_to_baostock(code: str) -> str:
    """Tushare 风格 600588.SH → Baostock 风格 sh.600588。

    已带 sh./sz./bj. 前缀的（兼容旧格式）原样返回。
    """
    code = code.strip().upper()
    if code.startswith(("SH.", "SZ.", "BJ.")):
        prefix = code[:2].lower()
        num = code[3:]
        return f"{prefix}.{num}"
    if code.startswith(("SH", "SZ", "BJ")) and "." not in code:
        # 兜底：极端情况（如 SH600588）不做处理，交给 Baostock 报错
        return code
    if "." in code:
        num, suffix = code.split(".", 1)
        suffix = suffix.lower()
        return f"{suffix}.{num}"
    # 纯数字：6/5 开头 → sh，其余 → sz
    if code.startswith(("6", "5")):
        return f"sh.{code}"
    return f"sz.{code}"


class BaostockClient(BaseFetcher):
    """Baostock 数据源客户端（继承 BaseFetcher）。

    与 TushareClient 对称：免登录 token，首次取数自动 login，会话结束 logout。
    """

    def __init__(self) -> None:
        self._bs = None
        self._logged_in = False

    # ---- 登录 / 登出 ----
    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        import baostock as bs

        self._bs = bs
        lg = bs.login()
        if lg.error_code != "0":
            raise ConnectionError(
                f"Baostock 登录失败: {lg.error_code} - {lg.error_msg}"
            )
        self._logged_in = True

    def _logout(self) -> None:
        if self._logged_in and self._bs is not None:
            self._bs.logout()
            self._logged_in = False

    # ---- BaseFetcher 统一接口 ----
    def fetch_daily_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        market_type: str = "stock",
        frequency: str = "d",
        adjustflag: str = "2",
    ) -> pd.DataFrame:
        """获取日线数据，返回标准 8 列 DataFrame。

        Args:
            code: Tushare 风格（600588.SH）或 Baostock 风格（sh.600588）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            market_type: stock/etf/index/hk（仅用于接口透明，Baostock 不区分）
            frequency: Baostock 频率，'d' 日线，分钟用 '5'/'15'/'30'/'60'
            adjustflag: 复权类型，'3' 不复权 / '1' 后复权 / '2' 前复权

        Returns:
            标准 8 列 DataFrame
        """
        bs_code = _tushare_to_baostock(code)
        # Baostock 要求日期为 YYYY-MM-DD 格式（与入参一致，不要去掉横杠）
        sd = start_date
        ed = end_date

        try:
            self._ensure_login()
            rs = self._bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,code,open,high,low,close,volume,amount",
                start_date=sd,
                end_date=ed,
                frequency=frequency,
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                raise RuntimeError(
                    f"Baostock 取数失败: {rs.error_code} - {rs.error_msg}"
                )

            rows = []
            while (rs.error_code == "0") & rs.next():
                rows.append(rs.get_row_data())

            df = pd.DataFrame(
                rows,
                columns=["date", "code", "open", "high", "low", "close", "volume", "amount"],
            )
            return self._to_standard_dataframe(df, code)
        finally:
            self._logout()

    @staticmethod
    def _to_standard_dataframe(df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Baostock 原始 DataFrame → 标准 8 列。

        列映射：
          date    → datetime (YYYY-MM-DD)
          code    → code（保留原始 Baostock 风格，便于追溯）
          volume  → volume（股，Baostock 原始即为股，无需换算）
          amount  → amount（元，Baostock 原始即为元，无需换算）
        """
        if df.empty:
            return df
        out = pd.DataFrame()
        out["datetime"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        out["open"] = df["open"].astype(float)
        out["high"] = df["high"].astype(float)
        out["low"] = df["low"].astype(float)
        out["close"] = df["close"].astype(float)
        out["volume"] = df["volume"].astype(float)
        out["amount"] = df["amount"].astype(float)
        out["code"] = code
        return out[["datetime", "open", "high", "low", "close", "volume", "amount", "code"]]
