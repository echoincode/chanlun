"""StockDB 本地数据源 fetcher（新增 stockdb 源）。

实现 BaseFetcher.fetch_daily_data 统一接口，返回标准 8 列 DataFrame：
datetime,open,high,low,close,volume,amount,code
（datetime 为 YYYY-MM-DD 字符串，volume 单位为股，amount 单位为元）。

数据来自本地 stockdb 服务（D:\\stockdb\\stockdb.exe，默认端口 7899），
通过 Python SDK（stock_sdk）访问。免 token、数据全本地、延迟极低。

代码格式：
  - 对外接受标准代码风格（600588.SH / 000001.SZ / 510300.SH / 00700.HK）
    与纯数字风格（600588）两种输入，内部统一转为纯数字（去掉后缀、前缀）。
  - stockdb 内部代码即纯数字（如 "600588"、"000001"），无交易所后缀。

复权：stockdb 的 rd.get_data 直接支持 qfq/hfq/""（不复权），与本项目 adj 参数对齐。

依赖：
  - 运行期需把 SDK 目录（D:\\stockdb\\pybao）加入 sys.path，且存在与 Python
    版本匹配的 stockdb.pyd（3.14 自由线程版用 3.14t+stockdb.pyd 改名）。
  - SDK 路径可通过环境变量 STOCKDB_SDK_PATH 覆盖，默认 r"D:\\stockdb\\pybao"。
  - 服务地址可通过 STOCKDB_HOST / STOCKDB_PORT 覆盖（默认 127.0.0.1:7899）。
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import pandas as pd

from src.data.base_fetcher import BaseFetcher
from src.utils.logger import log


def _ensure_sdk_importable() -> None:
    """将 stockdb SDK 目录加入 sys.path（仅一次）。"""
    sdk_path = os.environ.get("STOCKDB_SDK_PATH", r"D:\stockdb\pybao")
    if sdk_path and sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)


def _normalize_code(code: str) -> str:
    """标准代码风格 600588.SH / 纯数字 600588 → stockdb 纯数字代码 600588。

    已带交易所后缀的去掉后缀；港股 00700.HK 去后缀为 00700（stockdb 港股是否
    支持取决于本地库，调用方需自行确认）。
    """
    code = code.strip().upper()
    if "." in code:
        num = code.split(".", 1)[0]
    else:
        num = code
    # 去掉可能的 sh/sz/bj 前缀（兼容 sh.600588 旧风格）
    if num.lower().startswith(("SH", "SZ", "BJ")) and len(num) > 2:
        num = num[2:]
    return num


def _as_float(v) -> float:
    """把资金流字段安全转为 float；None / 空 / 非数值统一为 0.0。"""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class StockDBFetcher(BaseFetcher):
    """StockDB 本地数据源客户端（继承 BaseFetcher）。

    首次取数按需 import SDK 并 init 连接，连接单例复用（模块级 _RDK 缓存）。
    """

    _RDK = None  # 模块级单例，避免重复 init

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        self.host = host or os.environ.get("STOCKDB_HOST", "127.0.0.1")
        self.port = port if port is not None else int(os.environ.get("STOCKDB_PORT", "7899"))

    # ---- SDK 连接（懒加载 + 单例）----
    @classmethod
    def _get_rdk(cls, host: str, port: int):
        if cls._RDK is None:
            _ensure_sdk_importable()
            from stock_sdk import init, rd  # noqa: F401  (init 用于连接)

            init(host=host, port=port)
            cls._RDK = rd
        return cls._RDK

    def is_available(self) -> bool:
        """本地服务可达即视为可用（免 token）。"""
        try:
            self._get_rdk(self.host, self.port)
            # 轻量探测：尝试取一次股票代码全集
            self._get_rdk(self.host, self.port).get("股票代码")
            return True
        except Exception as e:  # noqa: BLE001
            log("STOCKDB", "WARN", f"可用性探测失败：{e}")
            return False

    # ---- BaseFetcher 统一接口 ----
    def fetch_daily_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        market_type: str = "stock",
        adj: str = "qfq",
        frequency: str = "daily",
        **kwargs,
    ) -> pd.DataFrame:
        """获取日线/分钟线数据，返回标准 8 列 DataFrame。

        优先用 rd.get_data 批量接口（支持复权、批量代码、区间、分钟聚合）；
        stockdb 的 get_data 已内置前/后复权与分钟聚合，无需本地计算。

        Args:
            code: 标准代码风格（600588.SH）或纯数字（600588）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            market_type: stock/etf/index/hk（stockdb 不强制区分，仅作日志透明）
            adj: None 未复权 / "qfq" 前复权 / "hfq" 后复权
            frequency: 日线 "daily" 或分钟周期 "5"/"15"/"30"/"60"（对应 stockdb 1m/5m/15m/30m/60m）

        Returns:
            标准 8 列 DataFrame：datetime,open,high,low,close,volume,amount,code
        """
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        code_num = _normalize_code(code)
        # stockdb 复权参数：空字符串表示不复权
        fq = adj if adj in ("qfq", "hfq") else ""
        # 频率映射：daily -> 1d；分钟 "5"/"15"/"30"/"60" -> 5m/15m/30m/60m
        freq_map = {"daily": "1d", "5": "5m", "15": "15m", "30": "30m", "60": "60m"}
        sd_freq = freq_map.get(frequency, "1d")

        rd = self._get_rdk(self.host, self.port)
        log("STOCKDB", "INFO",
            f"请求行情 [{code_num}] {sd}~{ed} freq={sd_freq} adj={adj}",
            code=code, market_type=market_type)

        data = rd.get_data(
            [code_num],
            start=sd,
            end=ed,
            frequency=sd_freq,
            fq=fq,
        )
        # get_data 返回 {code: DataFrame}；无数据时该 code 可能缺失或为空
        df = data.get(code_num) if isinstance(data, dict) else data
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            log("STOCKDB", "WARN", f"无数据返回 [{code_num}] {sd}~{ed}", code=code)
            return pd.DataFrame(
                columns=["datetime", "open", "high", "low", "close", "volume", "amount", "code"]
            )

        std = self._to_standard_dataframe(df, code)
        log("STOCKDB", "INFO", f"取数成功，返回 {len(std)} 条", code=code, rows=len(std))
        return std

    # ---- 资金流（个股日资金流向）----
    def fetch_money_flow(self, code: str, dates) -> dict:
        """获取个股日资金流（主力 / 超大 / 大 / 中 / 小单净流入及买卖额）。

        通过 stockdb 底层表 rd.get('资金流', code, date) 逐交易日查询（已实测可用；
        ApiDoc §10.2 的高层 get_money_flow 在本机当前版本返回空，故走底层表）。

        Args:
            code:  标准代码风格(600588.SH)或纯数字(600588)
            dates: 单个 YYYYMMDD 字符串/整数，或它们的列表（自动去重、取前 8 位）
        Returns:
            {date_8digit: {main_net, jumbo_net, big_net, mid_net, small_net,
                           main_in, main_out, retail_in, retail_out}, ...}
            无数据或查询失败的日期不出现在结果中；整体失败返回 {}。
            单位：元（与 rd.get 原始返回一致）。
        """
        code_num = _normalize_code(code)
        if isinstance(dates, (str, int)):
            dates = [dates]
        norm = []
        for d in dates:
            # 只保留数字后取前 8 位：兼容 "20260903" / "2026-09-03" / "2026-09-03 15:00:00"
            s = "".join(ch for ch in str(d) if ch.isdigit())[:8]
            if len(s) == 8 and s not in norm:
                norm.append(s)
        if not norm:
            return {}

        try:
            rd = self._get_rdk(self.host, self.port)
        except Exception as e:
            log("STOCKDB", "WARN", f"资金流连接失败 [{code_num}]: {e}")
            return {}

        result = {}
        for d in norm:
            try:
                rec = rd.get("资金流", code_num, str(d))
                if not rec:
                    continue
                # QueryResult 的 .get 会返回嵌套 QueryResult（非数值），先转真实 dict
                rec = dict(rec)
                result[d] = {
                    "main_net": _as_float(rec.get("main_net")),
                    "jumbo_net": _as_float(rec.get("jumbo_net")),
                    "big_net": _as_float(rec.get("big_net")),
                    "mid_net": _as_float(rec.get("mid_net")),
                    "small_net": _as_float(rec.get("small_net")),
                    "main_in": _as_float(rec.get("main_in")),
                    "main_out": _as_float(rec.get("main_out")),
                    "retail_in": _as_float(rec.get("retail_in")),
                    "retail_out": _as_float(rec.get("retail_out")),
                }
            except Exception as e:
                log("STOCKDB", "WARN", f"资金流查询失败 [{code_num}] {d}: {e}")
        if result:
            log("STOCKDB", "INFO", f"资金流获取成功 [{code_num}] {len(result)} 个交易日",
                code=code)
        else:
            log("STOCKDB", "WARN",
                f"资金流获取为空 [{code_num}] 查询 {len(norm)} 个交易日均无数据",
                code=code)
        return result

    @staticmethod
    def _to_standard_dataframe(df, code: str) -> pd.DataFrame:
        """stockdb 返回（list[dict] / DataFrame）→ 标准 8 列。

        列映射（stockdb 列为英文 date/code/open/high/low/close/volume/amount）：
          date    → datetime
                    日线：YYYYMMDD     → YYYY-MM-DD
                    分钟：YYYYMMDDhhmmss → YYYY-MM-DD HH:MM:SS
          volume  → volume（股，stockdb 原始即为股，无需换算）
          amount  → amount（元，stockdb 原始即为元，无需换算）
        """
        if isinstance(df, list):
            df = pd.DataFrame(df)
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame(
                columns=["datetime", "open", "high", "low", "close", "volume", "amount", "code"]
            )

        out = pd.DataFrame()
        date_col = "date" if "date" in df.columns else ("日期" if "日期" in df.columns else None)
        if date_col is None:
            raise KeyError(f"stockdb 返回缺少日期列，实际列：{list(df.columns)}")
        # 兼容日线(8位)与分钟线(14位)日期格式
        out["datetime"] = (
            df[date_col].astype(str)
            .str.replace(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})",
                         r"\1-\2-\3 \4:\5:\6", regex=True)
            .str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
        )
        for col in ("open", "high", "low", "close", "volume", "amount"):
            src = col if col in df.columns else None
            if src is None:
                # 中文列名兜底
                zh = {"open": "开盘", "high": "最高", "low": "最低",
                      "close": "收盘", "volume": "成交量", "amount": "成交额"}.get(col)
                src = zh if zh in df.columns else None
            out[col] = df[src].astype(float) if src else float("nan")
        out["code"] = code
        out = out.sort_values("datetime").reset_index(drop=True)
        return out[["datetime", "open", "high", "low", "close", "volume", "amount", "code"]]
