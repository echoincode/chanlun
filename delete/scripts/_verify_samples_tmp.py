"""Phase 0 · Step 0-4 验证：3 组黄金样本文件结构与内容（临时脚本，验证后删除）"""
import pandas as pd
import json
import os

SAMPLES = [
    'baostock_sh.600000_daily_2024-01-01_2024-12-31',
    'baostock_sh.000001_daily_2024-01-01_2024-12-31',
    'baostock_sh.600519_daily_2020-01-01_2024-12-31',
]
D = 'tests/golden_samples'
EXPECTED_COLS = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'amount', 'code']
EXPECTED_F_KEYS = {'index', 'type', 'high', 'low', 'datetime'}
EXPECTED_S_KEYS = {'start_idx', 'end_idx', 'start_type', 'end_type', 'direction', 'start_price', 'end_price'}

all_ok = True
for s in SAMPLES:
    csv_p = os.path.join(D, s + '.csv')
    json_p = os.path.join(D, s + '.expected.json')
    print(f'==== {s} ====')
    if not (os.path.exists(csv_p) and os.path.exists(json_p)):
        print(f'  ❌ missing files: csv={os.path.exists(csv_p)}, json={os.path.exists(json_p)}')
        all_ok = False
        continue
    df = pd.read_csv(csv_p)
    j = json.load(open(json_p, encoding='utf-8'))
    cols_ok = df.columns.tolist() == EXPECTED_COLS
    csv_size = os.path.getsize(csv_p)
    json_size = os.path.getsize(json_p)
    fractals_ok = isinstance(j.get('fractals'), list)
    segments_ok = isinstance(j.get('segments'), list)
    f0_ok = (len(j['fractals']) == 0) or (set(j['fractals'][0].keys()) == EXPECTED_F_KEYS)
    s0_ok = (len(j['segments']) == 0) or (set(j['segments'][0].keys()) == EXPECTED_S_KEYS)
    non_empty = (csv_size > 0) and (json_size > 0) and (len(df) > 0) and (len(j['fractals']) > 0) and (len(j['segments']) > 0)
    print(f'  CSV size: {csv_size} bytes, rows: {len(df)}, cols match: {cols_ok}')
    print(f'  CSV cols: {df.columns.tolist()}')
    print(f'  CSV datetime range: {df["datetime"].min()} ~ {df["datetime"].max()}')
    print(f'  JSON size: {json_size} bytes, fractals: {len(j["fractals"])}, segments: {len(j["segments"])}')
    print(f'  fractals is_list: {fractals_ok}, item0 keys ok: {f0_ok}')
    print(f'  segments is_list: {segments_ok}, item0 keys ok: {s0_ok}')
    print(f'  non_empty: {non_empty}')
    if not (cols_ok and fractals_ok and segments_ok and f0_ok and s0_ok and non_empty):
        all_ok = False
        print(f'  ❌ FAILED')
    else:
        print(f'  ✅ OK')
    # 打印第一个分型和第一个笔
    if j['fractals']:
        print(f'  fractal[0]: {j["fractals"][0]}')
    if j['segments']:
        print(f'  segment[0]: {j["segments"][0]}')
    print()

print(f'==== all samples ok: {all_ok} ====')
