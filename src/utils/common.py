"""缠论项目 · 通用工具函数（Phase 1 · Step 1-3）

以 app/utils.py 为统一基准，迁移 normalize_stock_code 和 get_market_type。
代码风格统一为标准格式（XXXXXX.SH / XXXXXX.SZ / XXXXXX.BJ / NNNNN.HK），
不再使用旧版 sh.600000 风格（数据源标准化后的用户决策）。

display_error/success/info/warning/metric 五个函数从未被任何模块引用
（已 grep 全项目确认），本文件不迁入，视为死代码；app/utils.py 原文件
本步不动，Phase 5/7 统一处理。

工作日辅助函数（get_previous_workday / is_workday / get_default_end_date）
为活代码（被 app/main.py 等引用），
一并迁入。
"""
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 工作日辅助（来源：app/utils.py，逻辑原样保留）
# ---------------------------------------------------------------------------
def get_previous_workday():
    """获取上一个工作日"""
    today = datetime.now()
    offset = 1
    while True:
        previous_day = today - timedelta(days=offset)
        if previous_day.weekday() < 5:
            return previous_day
        offset += 1


def is_workday(date=None):
    """判断是否为工作日"""
    if date is None:
        date = datetime.now()
    return date.weekday() < 5


def get_default_end_date():
    """获取默认结束日期：回退到最近的交易日（含节假日判断）。

    今天若是交易日则用今天，否则用上一个交易日（周末/法定节假日均生效）。
    """
    from src.data.trade_calendar import get_last_trading_day

    today = datetime.now().strftime("%Y-%m-%d")
    return datetime.strptime(get_last_trading_day(today), "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# 股票代码标准化（标准代码风格：XXXXXX.SH / XXXXXX.SZ / XXXXXX.BJ / NNNNN.HK）
# ---------------------------------------------------------------------------
def normalize_stock_code(code: str) -> str:
    """标准化股票代码为标准代码格式。

    支持的输入格式：
      - 纯数字 A 股 / ETF / 北交所：600000 / 000001 / 510300 / 159915 / 830799
      - 纯数字港股（≤5 位）：00700
      - 旧版带前缀（兼容）：sh.600000 / sz.000001 / bj.830799 → 自动转换
      - 已带标准后缀：600000.SH / 000001.SZ（原样返回，大小写规范化）
      - 港股带后缀：00700.HK（原样返回）

    Args:
        code: 用户输入的股票代码

    Returns:
        标准化后的标准代码格式（大写）
    """
    code = str(code).strip().upper()

    # 港股：纯数字且 ≤5 位（00700 等），补 .HK
    if code.isdigit() and len(code) <= 5:
        return f"{code}.HK"

    # 港股：已带 .HK 后缀
    if code.endswith(".HK"):
        return code

    # 旧版 sh./sz./bj. 前缀 → 转换为标准后缀
    if "." in code:
        # sh.600000 → 600000.SH
        for old_prefix in ("SH.", "SZ.", "BJ."):
            if code.startswith(old_prefix):
                num = code[len(old_prefix):]
                return f"{num}.{old_prefix.rstrip('.')}"
        # 已是 XXXXXX.SH 格式（含点但非旧前缀），原样返回
        return code

    # 纯 6 位数字 A 股 / ETF / 北交所
    if not code.isdigit() or len(code) != 6:
        return code

    return _suffix_for_a_share(code)


def _suffix_for_a_share(code: str) -> str:
    """6 位 A 股 / ETF / 北交所代码 → 加交易所后缀。

    规则（基于标准代码体系）：
      - 6 开头 → .SH（600000 上海主板、688xxx 科创板）
      - 5 开头 → .SH（510300 上海 ETF）
      - 159 开头 → .SZ（159915 深圳 ETF）
      - 0 / 3 开头 → .SZ（000001 深圳主板、300xxx 创业板）
      - 8 / 4 开头 → .BJ（830799 北交所）
    """
    if code.startswith("6") or code.startswith("5"):
        return f"{code}.SH"
    if code.startswith("159"):
        return f"{code}.SZ"
    if code.startswith("0") or code.startswith("3"):
        return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"):
        return f"{code}.BJ"
    return code


# ---------------------------------------------------------------------------
# 市场类型识别
# ---------------------------------------------------------------------------
def get_market_type(stock_code: str) -> str:
    """根据股票代码判断市场类型。

    返回值：'stock' / 'etf' / 'index' / 'hk'

    规则（基于标准代码格式 XXXXXX.SH/.SZ/.BJ/.HK）：
      - .HK 后缀或 ≤5 位纯数字 → 港股
      - 5xxxxx 或 159xxx → ETF
      - 指数：000xxx.SH（上证指数等）/ 399xxx.SZ / 880xxx
        ⚠️ 歧义处理：000001.SZ 是平安银行（股票），000001.SH 是上证指数（指数），
           用交易所后缀辅助区分——000 开头且 .SH 视为指数，000 开头且 .SZ 视为股票。
      - 其余 6 位数字 → A 股
    """
    code = str(stock_code).strip().upper()

    # 港股
    if code.endswith(".HK"):
        return "hk"
    if "." not in code and code.isdigit() and len(code) <= 5:
        return "hk"

    # 提取纯数字部分与后缀
    parts = code.split(".")
    num = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""

    if not num.isdigit() or len(num) != 6:
        return "stock"  # 未知格式兜底

    # ETF：5 开头（上海）或 159 开头（深圳）
    if num.startswith("5") or num.startswith("159"):
        return "etf"

    # 指数：000 开头且 .SH（上证指数 000001.SH / 沪深300 000300.SH）
    if num.startswith("000") and suffix == "SH":
        return "index"
    # 深证指数：399xxx / 880xxx
    if num.startswith("399") or num.startswith("880"):
        return "index"

    # 其余 → A 股（含北交所 8/4 开头，归入 stock）
    return "stock"
