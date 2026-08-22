"""一次性脚本：用 Tushare 获取 2025-01-01 到今天的日线数据（前复权）。

用法:
    python scripts/fetch_tushare_range.py [ts_code] [start] [end]

默认: ts_code=600588.SH, start=2025-01-01, end=今天
输出: cache/<ts_code 下划线>.csv （标准 8 列）
"""
from __future__ import annotations

import datetime as dt
import sys

from dotenv import load_dotenv

from src.data.tushare_fetcher import TushareClient

load_dotenv()

TS_CODE = sys.argv[1] if len(sys.argv) > 1 else "600588.SH"
START = sys.argv[2] if len(sys.argv) > 2 else "2025-01-01"
END = sys.argv[3] if len(sys.argv) > 3 else dt.date.today().isoformat()


def main() -> None:
    if not TushareClient.is_available():
        raise SystemExit("⚠️ 未配置 TUSHARE_TOKEN，无法取数")
    client = TushareClient()
    df = client.fetch_daily_data(
        code=TS_CODE,
        start_date=START,
        end_date=END,
        market_type="stock",
        adj="qfq",
    )
    if df.empty:
        print("⚠️ 返回为空，可能代码无效或无交易日数据")
        return
    out_name = TS_CODE.replace(".", "_") + ".csv"
    out_path = "cache/" + out_name
    df.to_csv(out_path, index=False)
    print(f"[OK] 已写入 {out_path}")
    print(f"     代码={TS_CODE}  区间={START}~{END}  行数={len(df)}")
    print(df.head(3).to_string(index=False))
    print("...")
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
