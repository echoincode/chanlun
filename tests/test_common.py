"""Phase 1 · Step 1-3 common.py 单元测试。

覆盖 normalize_stock_code / get_market_type 的输入输出，断言与
Tushare 代码体系一致。运行方式（仓库根）：
  python tests/test_common.py        # 直接运行（无需 pytest）
  python -m pytest tests/test_common.py -v   # 有 pytest 时
"""
import sys
import os

# 确保能 import src.utils.common（仓库根加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.common import (  # noqa: E402
    normalize_stock_code,
    get_market_type,
    is_workday,
    get_previous_workday,
    get_default_end_date,
)


# ---------------------------------------------------------------------------
# normalize_stock_code
# ---------------------------------------------------------------------------
def test_a_stock_sh():
    assert normalize_stock_code("600000") == "600000.SH"

def test_a_stock_sz():
    assert normalize_stock_code("000001") == "000001.SZ"

def test_etf_sh():
    assert normalize_stock_code("510300") == "510300.SH"

def test_etf_sz():
    assert normalize_stock_code("159915") == "159915.SZ"

def test_bj():
    assert normalize_stock_code("830799") == "830799.BJ"

def test_hk_pure_digits():
    assert normalize_stock_code("00700") == "00700.HK"

def test_hk_with_suffix():
    assert normalize_stock_code("00700.HK") == "00700.HK"

def test_old_prefix_sh():
    # 旧版 sh.600000 兼容 → 600000.SH
    assert normalize_stock_code("sh.600000") == "600000.SH"

def test_old_prefix_sz():
    assert normalize_stock_code("sz.000001") == "000001.SZ"

def test_old_prefix_bj():
    assert normalize_stock_code("bj.830799") == "830799.BJ"

def test_already_tushare_format():
    # 已带后缀原样返回（大小写规范化）
    assert normalize_stock_code("600000.sh") == "600000.SH"
    assert normalize_stock_code("000001.sz") == "000001.SZ"

def test_grey_board_688():
    # 科创板 688 开头 → .SH
    assert normalize_stock_code("688981") == "688981.SH"

def test_chinext_300():
    # 创业板 300 开头 → .SZ
    assert normalize_stock_code("300750") == "300750.SZ"


# ---------------------------------------------------------------------------
# get_market_type
# ---------------------------------------------------------------------------
def test_market_stock_sh():
    assert get_market_type("600000.SH") == "stock"

def test_market_stock_sz():
    # 000001.SZ 是平安银行（股票），不是指数
    assert get_market_type("000001.SZ") == "stock"

def test_market_etf_sh():
    assert get_market_type("510300.SH") == "etf"

def test_market_etf_sz():
    assert get_market_type("159915.SZ") == "etf"

def test_market_index_sh():
    # 000001.SH 是上证指数
    assert get_market_type("000001.SH") == "index"

def test_market_index_300():
    # 000300.SH 沪深300指数
    assert get_market_type("000300.SH") == "index"

def test_market_index_sz():
    # 399001.SZ 深证成指
    assert get_market_type("399001.SZ") == "index"

def test_market_hk_suffix():
    assert get_market_type("00700.HK") == "hk"

def test_market_hk_pure_digits():
    assert get_market_type("00700") == "hk"

def test_market_bj():
    # 北交所归入 stock
    assert get_market_type("830799.BJ") == "stock"


# ---------------------------------------------------------------------------
# 工作日函数
# ---------------------------------------------------------------------------
def test_is_workday_returns_bool():
    assert isinstance(is_workday(), bool)

def test_get_previous_workday():
    prev = get_previous_workday()
    assert prev.weekday() < 5  # 一定是工作日

def test_get_default_end_date_is_workday():
    d = get_default_end_date()
    # 默认结束日期必须是工作日
    assert d.weekday() < 5


if __name__ == "__main__":
    # 直接运行（无需 pytest）：遍历所有 test_ 函数并收集结果
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILED'}")
    sys.exit(1 if failures else 0)
