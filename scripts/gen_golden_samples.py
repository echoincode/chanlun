"""
Phase 0 · Step 0-4 黄金样本生成脚本

通过 sys.path 指向 project_backup/ 加载【原始算法】，统一经 Tushare 取数，
导出 3 组样本到 tests/golden_samples/：
  1. tushare_600000.SH_daily_2024-01-01_2024-12-31（浦发银行 A 股，1 年）
  2. tushare_510300.SH_daily_2024-01-01_2024-12-31（沪深300ETF，1 年）
  3. tushare_600519.SH_daily_2020-01-01_2024-12-31（贵州茅台，跨多年）

每组样本生成 2 个文件：
  - <prefix>.csv            原始 K 线，列：datetime,open,high,low,close,volume,amount,code
  - <prefix>.expected.json  分型+笔，结构见《分步执行清单》Step 0-4

运行方式（在仓库根 e:\\PrivateProject\\chanlun 下）：
  .\\venv\\Scripts\\python.exe scripts\\gen_golden_samples.py

⚠️ 本脚本通过 sys.path 优先加载 project_backup/ 内的原始代码作为基准，
   不读取改造区 src/ 等代码。备份目录始终保持只读冻结态。

📝 数据源决策（用户最终确认）：
  - 当前所有黄金样本的数据源【统一使用 Tushare】（经私有代理 ts-2.cwy666.com，
    已开通 daily / index_daily / fund_daily 三个接口）。覆盖 A 股（600000.SH）、
    ETF（510300.SH 沪深300ETF）、指数（000300.SH 沪深300）三类标的。
  - mootdx 已【弃用】；baostock 已【弃用】——本次改造不再使用任何 baostock 路径。
    此前 baostock 在本环境无法获取 ETF 行情（实测 sh.510300/sh.510180 等均返回
    空），故全量切换至 Tushare。
  - 列/单位对齐：Tushare 返回 ts_code/trade_date/open/high/low/close/vol(手)/
    amount(千元)，本脚本统一映射为文档规格 datetime,open,high,low,close,volume(股),
    amount(元),code(ts_code 原值)，保证与下游缠论算法、CSV 规格一致。
  - Tushare token：优先读环境变量 TUSHARE_TOKEN，缺失时回退到 tushare_client.py
    内置 demo token（私有代理 token）。
"""
import sys
import os
import json

import pandas as pd

# ---------------------------------------------------------------------------
# 路径设置：sys.path[0] = project_backup，保证加载的是【原始基准代码】
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(ROOT_DIR, 'project_backup')
OUTPUT_DIR = os.path.join(ROOT_DIR, 'tests', 'golden_samples')

if not os.path.isdir(BACKUP_DIR):
    raise SystemExit(f"备份目录不存在：{BACKUP_DIR}，请先完成 Step 0-2 备份")

sys.path.insert(0, BACKUP_DIR)

# 加载基准算法（行为应与备份目录原始代码 100% 一致）
from chanlun_processor import ChanlunProcessor  # noqa: E402

# Tushare 数据源（项目根 tushare_client.py，含私有代理地址）
sys.path.insert(0, ROOT_DIR)
from tushare_client import TushareClient  # noqa: E402


# ---------------------------------------------------------------------------
# 3 组样本规格（对应《分步执行清单》Step 0-4，全 Tushare 数据源）
# 覆盖：A 股 / ETF / A 股（跨多年），三类标的均有黄金样本
# code 使用 Tushare 格式（XXXXXX.SH / XXXXXX.SZ）
# ---------------------------------------------------------------------------
SAMPLES = [
    {
        'source': 'tushare',
        'code': '600000.SH',
        'freq': 'daily',
        'start': '2024-01-01',
        'end': '2024-12-31',
        'fetcher': 'tushare',
        'market_type': 'stock',
        'api': 'daily',
    },
    {
        'source': 'tushare',
        'code': '510300.SH',
        'freq': 'daily',
        'start': '2024-01-01',
        'end': '2024-12-31',
        'fetcher': 'tushare',
        'market_type': 'etf',
        'api': 'fund_daily',
    },
    {
        'source': 'tushare',
        'code': '600519.SH',
        'freq': 'daily',
        'start': '2020-01-01',
        'end': '2024-12-31',
        'fetcher': 'tushare',
        'market_type': 'stock',
        'api': 'daily',
    },
]


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------
def _get_tushare_client():
    token = os.environ.get('TUSHARE_TOKEN') or 'tsp_V3oG6xmzwoPGmfx4I4B1V63AMDqSIZfu3MpF2Gvd79s'
    return TushareClient(token)


def _tushare_to_standard(rows, code):
    """将 Tushare 返回字典列表映射为文档规格的 DataFrame。

    映射规则：
      trade_date -> datetime (YYYYMMDD -> YYYY-MM-DD)
      vol(手)    -> volume(股)   ×100
      amount(千元) -> amount(元) ×1000
      ts_code    -> code (原值)
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={'trade_date': 'datetime', 'vol': 'volume', 'ts_code': 'code'})
    df['datetime'] = df['datetime'].astype(str).str.slice(0, 10)
    df['volume'] = df['volume'].astype(float) * 100      # 手 -> 股
    df['amount'] = df['amount'].astype(float) * 1000     # 千元 -> 元
    df['code'] = code
    # 数值列转 float，避免科学计数法/整型影响下游比较
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[col] = df[col].astype(float)
    return df


def fetch_klines(sample):
    """通过 Tushare 私有代理取 K 线，并映射为文档规格 8 列。

    三类接口：daily(A股) / index_daily(指数) / fund_daily(ETF)。
    本脚本选用 A 股 + ETF + A 股（跨多年）组合，全部走 Tushare，不再使用
    baostock / mootdx（均已弃用）。
    """
    if sample['fetcher'] != 'tushare':
        raise ValueError(f"本脚本仅支持 tushare fetcher，收到：{sample['fetcher']}")

    client = _get_tushare_client()
    api = sample['api']
    start = sample['start'].replace('-', '')
    end = sample['end'].replace('-', '')
    rows = client.query(
        api,
        fields='ts_code,trade_date,open,high,low,close,vol,amount',
        ts_code=sample['code'],
        start_date=start,
        end_date=end,
    )
    return _tushare_to_standard(rows, sample['code'])


# ---------------------------------------------------------------------------
# 导出 CSV（列对齐文档规格）
# ---------------------------------------------------------------------------
def export_csv(df, csv_path):
    """导出原始 K 线 CSV，列对齐：datetime,open,high,low,close,volume,amount,code"""
    target_columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'amount', 'code']
    out = df.copy()
    for col in target_columns:
        if col not in out.columns:
            out[col] = None
    out = out[target_columns]
    # datetime 转字符串，便于下游严格字符串比较
    out['datetime'] = out['datetime'].astype(str)
    out.to_csv(csv_path, index=False, encoding='utf-8')


# ---------------------------------------------------------------------------
# 导出期望 JSON（分型 + 笔）
# ---------------------------------------------------------------------------
def export_expected_json(processor, json_path):
    """导出期望分型/笔 JSON

    fractals: list of {index, type, high, low, datetime}  ← 四重筛选后的最终分型
    segments: list of {start_idx, end_idx, start_type, end_type, direction,
                       start_price, end_price}  ← identify_segments 输出的笔
    """
    fractals = []
    if processor.fractals_data is not None:
        is_f = processor.fractals_data[processor.fractals_data['is_fractal']]
        for idx, row in is_f.iterrows():
            fractals.append({
                'index': int(idx),
                'type': str(row['fractal_type']),
                'high': float(row['high']),
                'low': float(row['low']),
                'datetime': str(row['datetime']),
            })

    segments = []
    if hasattr(processor, 'segments') and processor.segments:
        for seg in processor.segments:
            segments.append({
                'start_idx': int(seg['start_idx']),
                'end_idx': int(seg['end_idx']),
                'start_type': str(seg['start_type']),
                'end_type': str(seg['end_type']),
                'direction': str(seg['direction']),
                'start_price': float(seg['start_price']),
                'end_price': float(seg['end_price']),
            })

    output = {'fractals': fractals, 'segments': segments}
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"输出目录：{OUTPUT_DIR}")
    print(f"基准代码目录：{BACKUP_DIR}")
    print()

    failed = []
    for i, sample in enumerate(SAMPLES, 1):
        prefix = f"{sample['source']}_{sample['code']}_{sample['freq']}_{sample['start']}_{sample['end']}"
        csv_path = os.path.join(OUTPUT_DIR, f"{prefix}.csv")
        json_path = os.path.join(OUTPUT_DIR, f"{prefix}.expected.json")

        print(f"[{i}/{len(SAMPLES)}] 样本：{prefix}")
        print(f"  取数：{sample['fetcher']} / {sample['code']} / {sample['start']} ~ {sample['end']}")

        try:
            data = fetch_klines(sample)
        except Exception as e:
            print(f"  ❌ 取数失败：{e}")
            failed.append(prefix)
            print()
            continue

        if data is None or data.empty:
            print(f"  ❌ 数据为空，跳过")
            failed.append(prefix)
            print()
            continue

        print(f"  ✅ 取到 {len(data)} 根 K 线")

        # 导出原始 K 线 CSV
        export_csv(data, csv_path)
        print(f"  ✅ CSV 已写入：{csv_path}")

        # 缠论分析（加载基准算法，行为应与备份目录原始代码 100% 一致）
        processor = ChanlunProcessor()
        processor.process_klines(data)

        # 导出期望 JSON
        export_expected_json(processor, json_path)
        if processor.fractals_data is not None:
            fractal_count = int(processor.fractals_data['is_fractal'].sum())
        else:
            fractal_count = 0
        segment_count = len(processor.segments) if hasattr(processor, 'segments') else 0
        print(f"  ✅ JSON 已写入：{json_path}（fractals={fractal_count}, segments={segment_count}）")
        print()

    print("==== 全部样本生成完毕 ====")
    if failed:
        print(f"⚠️ 以下样本生成失败，请检查环境/网络后重试：{failed}")
        sys.exit(1)
    print("✅ 全部样本生成成功")


if __name__ == '__main__':
    main()
