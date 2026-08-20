"""Tushare 数据源 fetcher（Phase 3 · Step 3-3）。

迁移自项目根 tushare_client.py，改造点：
  1. 继承 BaseFetcher，实现 fetch_daily_data 统一接口（返回标准 8 列 DataFrame）；
  2. token/api_url/timeout 等默认值改从 src.config.settings 读取，删除原硬编码 token；
  3. 吸收 gen_golden_samples.py 的 _tushare_to_standard 列映射逻辑为 _to_standard_dataframe；
  4. 原有 query/daily/index_daily/fund_daily/pro_bar/trade_cal 方法体**完全不动**；
  5. _demo() 冒烟测试 print 保留原样，token 改读环境变量。

原有取数逻辑（三接口分派 daily/fund_daily/index_daily、token 鉴权、retry、限流）
完全不动。新增的 fetch_daily_data 是高层封装，不改动底层取数方法。
"""
from __future__ import annotations

import os
import time
from typing import Any, Iterable

import pandas as pd
import requests

from src.config.settings import (
    TUSHARE_API_URL,
    TUSHARE_MAX_RETRIES,
    TUSHARE_RETRY_DELAY,
    TUSHARE_TIMEOUT,
    TUSHARE_TOKEN,
)
from src.data.base_fetcher import BaseFetcher


# 市场类型 → Tushare 接口名分派
_MARKET_API_MAP = {
    "stock": "daily",
    "etf": "fund_daily",
    "index": "index_daily",
}


class TushareClient(BaseFetcher):
    """Tushare 私有代理客户端（继承 BaseFetcher）。

    说明：
    - 该部署将官方 Tushare Pro 接口（http://api.tushare.pro）代理到私有地址，
      调用时只需把请求 URL 换成 https://ts-2.cwy666.com 即可，token 用法不变。
    - 接口协议与官方一致：POST JSON，body 含 api_name / token / params / fields，
      返回 {"code", "msg", "data": {"fields", "items"}}
    - 频率限制：120 次/分钟。
    """

    # 关键：更换请求地址（不使用官方 api.tushare.pro，改用私有代理地址）
    DEFAULT_API_URL = TUSHARE_API_URL

    @staticmethod
    def is_available() -> bool:
        """无需实例化即可检查 token 是否就绪（供 runner 提前拦截）。"""
        return bool(TUSHARE_TOKEN)

    def __init__(
        self,
        token: str | None = None,
        api_url: str = DEFAULT_API_URL,
        timeout: int = TUSHARE_TIMEOUT,
        max_retries: int = TUSHARE_MAX_RETRIES,
        retry_delay: float = TUSHARE_RETRY_DELAY,
    ) -> None:
        # token 优先显式传入，否则从 settings（环境变量 TUSHARE_TOKEN）读取
        self.token = token if token is not None else TUSHARE_TOKEN
        if not self.token:
            raise ValueError(
                "Tushare token 缺失：请设置环境变量 TUSHARE_TOKEN，或在实例化时传入 token 参数"
            )
        self.api_url = api_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session = requests.Session()
        # 简单的客户端限速，避免触发 120 次/分钟限制
        self._min_interval = 60.0 / 120.0  # 每次调用至少间隔 0.5s
        self._last_call_ts = 0.0

    def _ratelimit(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def query(
        self,
        api_name: str,
        fields: str | Iterable[str] = "",
        **params: Any,
    ) -> list[dict[str, Any]]:
        """调用任意 Tushare 接口，返回以字段名为 key 的字典列表。

        Args:
            api_name: 接口名，如 "trade_cal"、"daily"、"pro_bar" 等。
            fields:   需要的字段，可传字符串 "ts_code,close" 或列表。
            **params: 接口参数，如 exchange="SSE", start_date="20240101"。
        """
        if isinstance(fields, (list, tuple, set)):
            fields = ",".join(fields)

        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params,
            "fields": fields or "",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._ratelimit()
            try:
                resp = self._session.post(self.api_url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                body = resp.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                    continue
                raise ConnectionError(f"[{api_name}] 请求失败: {e}") from e

            code = body.get("code")
            if code != 0:
                # 代理可能返回非 0 code（如 token 无效、限流、参数错误）
                raise RuntimeError(
                    f"[{api_name}] 接口返回错误 code={code}, msg={body.get('msg')}"
                )

            data = body.get("data") or {}
            flds = data.get("fields") or []
            items = data.get("items") or []
            return [dict(zip(flds, row)) for row in items]

        # 理论不可达
        raise RuntimeError(f"[{api_name}] 未知错误: {last_err}")

    # ---- 下面是几个常用接口的便捷封装，便于测试 ----

    def trade_cal(
        self,
        exchange: str = "SSE",
        start_date: str = "20240101",
        end_date: str = "20240110",
    ) -> list[dict[str, Any]]:
        """交易日历。"""
        return self.query(
            "trade_cal",
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
        )

    def daily(
        self,
        ts_code: str = "000001.SZ",
        start_date: str = "20240101",
        end_date: str = "20240110",
    ) -> list[dict[str, Any]]:
        """日线行情。"""
        return self.query(
            "daily",
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    def pro_bar(
        self,
        ts_code: str = "000001.SZ",
        start_date: str = "20240101",
        end_date: str = "20240110",
        freq: str = "D",
        asset: str = "E",
        adj: str | None = None,
    ) -> list[dict[str, Any]]:
        """通用行情接口（日/周/月/分钟），支持复权。

        adj: None 未复权 / "qfq" 前复权 / "hfq" 后复权（仅 asset='E' 股票支持）。
        """
        return self.query(
            "pro_bar",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
            asset=asset,
            adj=adj,
        )

    def index_daily(
        self,
        ts_code: str = "000300.SH",
        start_date: str = "20240101",
        end_date: str = "20240110",
    ) -> list[dict[str, Any]]:
        """指数日线行情（如 000300.SH 沪深300）。"""
        return self.query(
            "index_daily",
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    def fund_daily(
        self,
        ts_code: str = "510300.SH",
        start_date: str = "20240101",
        end_date: str = "20240110",
    ) -> list[dict[str, Any]]:
        """ETF/基金日线行情（如 510300.SH 沪深300ETF）。"""
        return self.query(
            "fund_daily",
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    # ---- BaseFetcher 统一接口实现（新增，不改动原有取数方法） ----

    def fetch_daily_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        market_type: str = "stock",
        adj: str = "qfq",
    ) -> pd.DataFrame:
        """BaseFetcher 统一接口：获取日线数据，返回标准 8 列 DataFrame。

        统一走 pro_bar 通用行情接口，并默认前复权（adj="qfq"），
        与 Baostock 默认前复权（adjustflag="2"）口径对齐，消除展示不一致。

        注意：
          - adj=None 未复权 / "qfq" 前复权 / "hfq" 后复权（仅股票支持）
          - 指数/基金（asset 非 'E'）pro_bar 不支持 adj，自动降级为 None
          - hk：tushare 港股需单独权限，直接报错

        列映射（吸收自 gen_golden_samples.py 的 _tushare_to_standard）：
          trade_date → datetime (YYYYMMDD → YYYY-MM-DD)
          vol(手)    → volume(股)   ×100
          amount(千元) → amount(元) ×1000
          ts_code    → code (原值)
        """
        if market_type == "hk":
            raise ValueError(
                "Tushare 不支持港股（需单独权限），请使用 A股/ETF/指数"
            )
        # asset 映射：stock→E, etf→FD, index→I
        asset = {"stock": "E", "etf": "FD", "index": "I"}.get(market_type, "E")
        # qfq/hfq 仅股票支持，指数/基金强制不复权
        if asset != "E":
            adj = None
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        try:
            rows = self.pro_bar(
                ts_code=code,
                start_date=start,
                end_date=end,
                freq="D",
                asset=asset,
                adj=adj,
            )
        except RuntimeError as e:
            # pro_bar 需要积分权限（40101 接口未授权）。权限不足时优雅降级到
            # 原 daily/fund_daily/index_daily（不复权），保证功能不中断；
            # 此时无法与 Baostock 前复权对齐，仅在有 pro_bar 权限时生效。
            if "40101" in str(e):
                api = _MARKET_API_MAP.get(market_type, "daily")
                rows = self.query(
                    api,
                    fields="ts_code,trade_date,open,high,low,close,vol,amount",
                    ts_code=code,
                    start_date=start,
                    end_date=end,
                )
            else:
                raise
        return self._to_standard_dataframe(rows, code)

    @staticmethod
    def _to_standard_dataframe(rows: list[dict[str, Any]], code: str) -> pd.DataFrame:
        """将 Tushare 返回字典列表映射为标准 8 列 DataFrame。

        映射规则与 gen_golden_samples.py 的 _tushare_to_standard 一致，
        确保改造后取数结果与黄金样本 CSV 完全对齐。
        """
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = df.rename(columns={"trade_date": "datetime", "vol": "volume", "ts_code": "code"})
        df["datetime"] = df["datetime"].astype(str).str.slice(0, 10)
        df["volume"] = df["volume"].astype(float) * 100      # 手 → 股
        df["amount"] = df["amount"].astype(float) * 1000     # 千元 → 元
        df["code"] = code
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = df[col].astype(float)
        return df[["datetime", "open", "high", "low", "close", "volume", "amount", "code"]]


def _demo() -> None:
    """简单冒烟测试：验证连接、token、限流是否正常。"""
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("⚠️ 未设置 TUSHARE_TOKEN 环境变量，_demo 跳过实盘调用")
        return
    client = TushareClient(token)

    print("== trade_cal ==")
    for row in client.trade_cal(start_date="20240108", end_date="20240110"):
        print(row)

    print("\n== daily (000001.SZ) ==")
    for row in client.daily(ts_code="000001.SZ", start_date="20240108", end_date="20240110"):
        print(row)


if __name__ == "__main__":
    _demo()
