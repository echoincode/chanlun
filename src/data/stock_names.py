"""全市场标的代码 → 名称映射（带本地缓存）。

用于：
  1. Web 图表标题/信息区展示品种中文名；
  2. 监控推送模板中把 `600519.SH` 显示为「600519.SH 贵州茅台」。

实现：
  - 从本地缓存 `cache/stock_names.json` 读取（毫秒级，无网络 IO）；
  - baostock 数据源已移除，当前不再联网刷新，待接入 stockdb 名称接口后恢复；
  - 支持 `sh.600000` / `600000.SH` / `600000` 三种输入风格。
"""
from __future__ import annotations

import json
import os
from typing import Optional

_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cache",
    "stock_names.json",
)

_code2name: Optional[dict] = None


def _to_cache_key(code: str) -> str:
    """600519.SH / 600519 / sh.600519 → sh.600519（既有缓存文件的 key 风格）。"""
    code = code.strip().lower().replace(".sh", ".sh")
    if code.startswith(("sh.", "sz.", "bj.")):
        return code
    if "." in code:
        num, suffix = code.split(".", 1)
        return f"{suffix}.{num}"
    if code.startswith(("6", "5")):
        return f"sh.{code}"
    if code.startswith(("0", "3", "2", "8", "4")):
        return f"sz.{code}"
    return f"sh.{code}"


def load_stock_names(force_refresh: bool = False) -> dict:
    """加载代码→名称映射（仅读本地缓存 cache/stock_names.json）。

    baostock 数据源已移除，当前不再联网刷新；待接入 stockdb 名称接口后
    可恢复刷新能力。

    Args:
        force_refresh: 保留参数以兼容既有调用方（当前等同强制重新读盘）。
    Returns:
        映射字典，key 为 sh.600000 风格（沿用既有缓存格式），value 为中文名。
    """
    global _code2name
    if _code2name is not None and not force_refresh:
        return _code2name

    mapping: dict = {}
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            mapping = {}

    _code2name = mapping
    return _code2name


def get_stock_name(code: str, default: Optional[str] = None) -> str:
    """根据代码返回中文名，未知时返回 `default`（默认回退为原代码）。"""
    mapping = load_stock_names()
    key = _to_cache_key(code)
    name = mapping.get(key)
    if name:
        return f"{code} {name}"
    return default if default is not None else code


if __name__ == "__main__":
    names = load_stock_names(force_refresh=True)
    print(f"载入 {len(names)} 条映射")
    print(get_stock_name("sh.600000"))
    print(get_stock_name("600519.SH"))
