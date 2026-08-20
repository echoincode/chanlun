"""临时验证：Phase 4 · Step 4-3 runner 黄金样本一致性（临时脚本，后期统一清理）。

对 3 组黄金样本：runner.fetch_data() + runner.analyze()，
将 summary 中注入的 fractals/segments 与 .expected.json 逐条对比。

运行方式（仓库根）：
  .\\venv\\Scripts\\python.exe _verify_runner_tmp.py
"""
import json
import math
import os
import sys

# ⚠️ 必须在 import src.* 之前设置：settings.py 在导入时即读取环境变量并冻结
os.environ.setdefault(
    "TUSHARE_TOKEN", "tsp_V3oG6xmzwoPGmfx4I4B1V63AMDqSIZfu3MpF2Gvd79s"
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.cli.runner import fetch_data, analyze  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "golden_samples")

SAMPLES = [
    {"code": "600000.SH", "start": "2024-01-01", "end": "2024-12-31"},
    {"code": "510300.SH", "start": "2024-01-01", "end": "2024-12-31"},
    {"code": "600519.SH", "start": "2020-01-01", "end": "2024-12-31"},
]


def _close(a, b, rel_tol=1e-9):
    return math.isclose(float(a), float(b), rel_tol=rel_tol)


def _check_fractals(got, exp, prefix):
    if len(got) != len(exp):
        return f"分型数量不一致: got={len(got)} exp={len(exp)}"
    for i, (g, e) in enumerate(zip(got, exp)):
        if int(g["index"]) != int(e["index"]):
            return f"分型[{i}] index 不一致: got={g['index']} exp={e['index']}"
        if str(g["type"]) != str(e["type"]):
            return f"分型[{i}] type 不一致: got={g['type']} exp={e['type']}"
        if str(g["datetime"]) != str(e["datetime"]):
            return f"分型[{i}] datetime 不一致: got={g['datetime']} exp={e['datetime']}"
        if not _close(g["high"], e["high"]):
            return f"分型[{i}] high 不一致: got={g['high']} exp={e['high']}"
        if not _close(g["low"], e["low"]):
            return f"分型[{i}] low 不一致: got={g['low']} exp={e['low']}"
    return None


def _check_segments(got, exp, prefix):
    if len(got) != len(exp):
        return f"笔数量不一致: got={len(got)} exp={len(exp)}"
    for i, (g, e) in enumerate(zip(got, exp)):
        for key in ["start_idx", "end_idx"]:
            if int(g[key]) != int(e[key]):
                return f"笔[{i}] {key} 不一致: got={g[key]} exp={e[key]}"
        for key in ["start_type", "end_type", "direction"]:
            if str(g[key]) != str(e[key]):
                return f"笔[{i}] {key} 不一致: got={g[key]} exp={e[key]}"
        for key in ["start_price", "end_price"]:
            if not _close(g[key], e[key]):
                return f"笔[{i}] {key} 不一致: got={g[key]} exp={e[key]}"
    return None


def main() -> int:
    all_ok = True
    for s in SAMPLES:
        prefix = f"tushare_{s['code']}_daily_{s['start']}_{s['end']}"
        json_path = os.path.join(GOLDEN_DIR, f"{prefix}.expected.json")
        if not os.path.exists(json_path):
            print(f"SKIP {prefix}: 期望 JSON 不存在 {json_path}")
            all_ok = False
            continue

        with open(json_path, "r", encoding="utf-8") as f:
            expected = json.load(f)

        df = fetch_data(s["code"], s["start"], s["end"])
        result_df, summary = analyze(df)

        err = _check_fractals(summary["fractals"], expected["fractals"], prefix)
        if err is None:
            err = _check_segments(summary["segments"], expected["segments"], prefix)

        if err is None:
            print(
                f"PASS {prefix}: fractals={len(summary['fractals'])} "
                f"segments={len(summary['segments'])} 与期望 100% 一致"
            )
        else:
            all_ok = False
            print(f"FAIL {prefix}: {err}")
            print(f"  got fractals={len(summary['fractals'])} "
                  f"exp fractals={len(expected['fractals'])}")
            print(f"  got segments={len(summary['segments'])} "
                  f"exp segments={len(expected['segments'])}")

    print("\n" + ("ALL PASS ✅" if all_ok else "SOME FAILED ❌"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
