"""Phase 3 · Step 3-4 数据层一致性验证（Tushare 黄金样本对比）。

用 src/data/tushare_fetcher 的 fetch_daily_data 取数，对比
tests/golden_samples/*.csv，验证迁移后取数逻辑 + 列映射与黄金样本完全一致。

运行方式（仓库根）：
  python tests/verify_tushare_fetcher.py

token 仅读环境变量 TUSHARE_TOKEN（不内置任何硬编码 token，避免凭据泄露）。
"""
import os
import sys

import pandas as pd

# 确保能 import src.data.tushare_fetcher
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.tushare_fetcher import TushareClient  # noqa: E402


# 3 组黄金样本规格（与 tests/golden_samples 文件名前缀对齐）
SAMPLES = [
    {
        "code": "600000.SH",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "market_type": "stock",
        "prefix": "tushare_600000.SH_daily_2024-01-01_2024-12-31",
    },
    {
        "code": "510300.SH",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "market_type": "etf",
        "prefix": "tushare_510300.SH_daily_2024-01-01_2024-12-31",
    },
    {
        "code": "600519.SH",
        "start": "2020-01-01",
        "end": "2024-12-31",
        "market_type": "stock",
        "prefix": "tushare_600519.SH_daily_2020-01-01_2024-12-31",
    },
]

GOLDEN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "golden_samples",
)


def main() -> int:
    # token 仅从环境变量读取，禁止硬编码（避免凭据泄露进仓库）
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        print("✗ 未设置 TUSHARE_TOKEN 环境变量，无法运行验证；请先配置后再试。")
        return 1
    client = TushareClient(token=token)

    all_ok = True
    for s in SAMPLES:
        csv_path = os.path.join(GOLDEN_DIR, s["prefix"] + ".csv")
        if not os.path.exists(csv_path):
            print(f"SKIP {s['prefix']}: 黄金样本 CSV 不存在 {csv_path}")
            all_ok = False
            continue

        expected = pd.read_csv(csv_path)

        try:
            got = client.fetch_daily_data(
                s["code"], s["start"], s["end"], s["market_type"]
            )
        except Exception as e:
            print(f"FAIL {s['prefix']}: 取数异常 {e}")
            all_ok = False
            continue

        # 黄金样本 CSV 的 datetime 列被 pandas 解析为 int64，
        # fetcher 返回 str；值一致但类型不同，统一为字符串后再比较
        expected = expected.copy()
        expected["datetime"] = expected["datetime"].astype(str)

        # 对比：reset_index 后逐行逐列比较，check_dtype=False 允许类型差异
        try:
            pd.testing.assert_frame_equal(
                got.reset_index(drop=True),
                expected.reset_index(drop=True),
                check_dtype=False,
            )
            print(f"PASS {s['prefix']}: rows={len(got)}, 与黄金样本完全一致")
        except AssertionError as e:
            all_ok = False
            print(f"FAIL {s['prefix']}: 与黄金样本不一致")
            print(f"  got rows={len(got)}, expected rows={len(expected)}")
            print(f"  diff: {str(e)[:200]}")

    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
