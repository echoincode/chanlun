"""全量一致性回归测试（Phase 7 · Step 7-4）

对比 3 组黄金样本的改造后代码分析结果与期望 JSON 是否一致。
验证范围：src/core/chanlun_processor.py + src/cli/runner.py
"""
from __future__ import annotations

import json
import os
import sys
import math

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cli.runner import analyze

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden_samples")

SAMPLES = [
    ("600000.SH", "2024-01-01", "2024-12-31"),
    ("510300.SH", "2024-01-01", "2024-12-31"),
    ("600519.SH", "2020-01-01", "2024-12-31"),
]


def load_expected(code, start, end):
    prefix = f"tushare_{code}_daily_{start}_{end}"
    path = os.path.join(GOLDEN_DIR, f"{prefix}.expected.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_csv(code, start, end):
    prefix = f"tushare_{code}_daily_{start}_{end}"
    path = os.path.join(GOLDEN_DIR, f"{prefix}.csv")
    return pd.read_csv(path, dtype={"datetime": str})


def compare_numeric(actual, expected, rel_tol=1e-9):
    if isinstance(actual, (int, float)):
        return math.isclose(actual, expected, rel_tol=rel_tol)
    return actual == expected


def verify_sample(code, start, end):
    print(f"\n{'='*60}")
    print(f"验证样本: {code} ({start} ~ {end})")
    print(f"{'='*60}")

    expected = load_expected(code, start, end)
    df = load_csv(code, start, end)

    # 使用改造后代码分析
    result_df, summary = analyze(df)

    actual_fractals = summary.get("fractals", [])
    actual_segments = summary.get("segments", [])

    expected_fractals = expected.get("fractals", [])
    expected_segments = expected.get("segments", [])

    all_pass = True

    # 1. 对比分型数量
    if len(actual_fractals) != len(expected_fractals):
        print(f"❌ 分型数量不一致: 实际 {len(actual_fractals)} vs 期望 {len(expected_fractals)}")
        all_pass = False
    else:
        print(f"✅ 分型数量一致: {len(actual_fractals)}")

    # 2. 对比笔数量
    if len(actual_segments) != len(expected_segments):
        print(f"❌ 笔数量不一致: 实际 {len(actual_segments)} vs 期望 {len(expected_segments)}")
        all_pass = False
    else:
        print(f"✅ 笔数量一致: {len(actual_segments)}")

    # 3. 对比分型详细数据
    for i, (actual_f, expected_f) in enumerate(zip(actual_fractals, expected_fractals)):
        for key in expected_f:
            actual_val = actual_f.get(key)
            expected_val = expected_f[key]
            if not compare_numeric(actual_val, expected_val):
                print(f"❌ 分型[{i}].{key} 不一致: 实际 {actual_val} vs 期望 {expected_val}")
                all_pass = False

    if all_pass:
        print("✅ 分型详细数据一致")

    # 4. 对比笔详细数据
    for i, (actual_s, expected_s) in enumerate(zip(actual_segments, expected_segments)):
        for key in expected_s:
            actual_val = actual_s.get(key)
            expected_val = expected_s[key]
            if not compare_numeric(actual_val, expected_val):
                print(f"❌ 笔[{i}].{key} 不一致: 实际 {actual_val} vs 期望 {expected_val}")
                all_pass = False

    if all_pass:
        print("✅ 笔详细数据一致")

    return all_pass


def main():
    print("=" * 60)
    print("缠论项目 v4 全量一致性回归测试")
    print("验证改造后代码与黄金样本期望一致")
    print("=" * 60)

    results = []
    for code, start, end in SAMPLES:
        passed = verify_sample(code, start, end)
        results.append((code, passed))

    print(f"\n{'='*60}")
    print("回归测试总结")
    print(f"{'='*60}")

    all_passed = True
    for code, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {code}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n🎉 全部 3 组样本验证通过！")
        return 0
    else:
        print("\n❌ 存在验证失败的样本，请检查日志")
        return 1


if __name__ == "__main__":
    sys.exit(main())
