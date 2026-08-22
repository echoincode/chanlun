"""全市场标的代码 → 名称映射（带本地缓存）。

用于：
  1. Web 图表标题/信息区展示品种中文名；
  2. 监控推送模板中把 `600519.SH` 显示为「600519.SH 贵州茅台」。

实现：
  - 首次调用 `query_all_stock()` 拉取全市场映射，写入 `cache/stock_names.json`；
  - 之后从本地缓存读取（毫秒级，无网络 IO）；
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


def _tushare_to_baostock(code: str) -> str:
    """600519.SH / 600519 / sh.600519 → sh.600519（baostock key）。"""
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
    """加载代码→名称映射（优先本地缓存）。

    Args:
        force_refresh: True 时强制重新查询 Baostock 并覆盖缓存。
    Returns:
        映射字典，key 为 baostock 风格（sh.600000），value 为中文名。
    """
    global _code2name
    if _code2name is not None and not force_refresh:
        return _code2name

    # 1) 尝试读本地缓存
    if not force_refresh and os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _code2name = json.load(f)
            return _code2name
        except Exception:
            _code2name = None

    # 2) 缓存缺失/刷新：查询 Baostock
    import baostock as bs
    from datetime import datetime as _dt, timedelta as _td

    lg = bs.login()
    try:
        # query_all_stock() 不带 day 参数时按"当前交易日"查，非交易日返回空；
        # 且 baostock 的 rs.get_data() 在新版 pandas 下因 .append 废弃而报错，
        # 故手动遍历 rows（fields + get_row_data）并回退到最近 7 个自然日。
        mapping: dict = {}
        for back in range(0, 8):
            day = (_dt.now() - _td(days=back)).strftime("%Y-%m-%d")
            rs = bs.query_all_stock(day=day)
            if not rs or not getattr(rs, "fields", None):
                continue
            fields = list(rs.fields)
            if "code" not in fields or "code_name" not in fields:
                continue
            code_idx, name_idx = fields.index("code"), fields.index("code_name")
            rows = []
            while rs.next():
                row = rs.get_row_data()
                if row and len(row) > max(code_idx, name_idx):
                    rows.append((row[code_idx], row[name_idx]))
            if rows:
                mapping = dict(rows)
                break
    finally:
        bs.logout()

    # 3) 写缓存
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    _code2name = mapping
    return _code2name


def get_stock_name(code: str, default: Optional[str] = None) -> str:
    """根据代码返回中文名，未知时返回 `default`（默认回退为原代码）。"""
    mapping = load_stock_names()
    key = _tushare_to_baostock(code)
    name = mapping.get(key)
    if name:
        return f"{code} {name}"
    return default if default is not None else code


if __name__ == "__main__":
    names = load_stock_names(force_refresh=True)
    print(f"载入 {len(names)} 条映射")
    print(get_stock_name("sh.600000"))
    print(get_stock_name("600519.SH"))
