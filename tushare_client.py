"""Tushare 私有代理测试类。

说明：
- 该部署将官方 Tushare Pro 接口（http://api.tushare.pro）代理到私有地址，
  调用时只需把请求 URL 换成 https://ts-2.cwy666.com 即可，token 用法不变。
- 接口协议与官方一致：POST JSON，body 含 api_name / token / params / fields，
  返回 {"code", "msg", "data": {"fields", "items"}}
- 频率限制：120 次/分钟。
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import requests


class TushareClient:
    # 关键：更换请求地址（不使用官方 api.tushare.pro，改用私有代理地址）
    DEFAULT_API_URL = "https://ts-2.cwy666.com"

    def __init__(
        self,
        token: str,
        api_url: str = DEFAULT_API_URL,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.token = token
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
    ) -> list[dict[str, Any]]:
        """通用行情接口（日/周/月/分钟）。"""
        return self.query(
            "pro_bar",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
            asset=asset,
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


def _demo() -> None:
    """简单冒烟测试：验证连接、token、限流是否正常。"""
    token = "tsp_V3oG6xmzwoPGmfx4I4B1V63AMDqSIZfu3MpF2Gvd79s"
    client = TushareClient(token)

    print("== trade_cal ==")
    for row in client.trade_cal(start_date="20240108", end_date="20240110"):
        print(row)

    print("\n== daily (000001.SZ) ==")
    for row in client.daily(ts_code="000001.SZ", start_date="20240108", end_date="20240110"):
        print(row)


if __name__ == "__main__":
    _demo()
