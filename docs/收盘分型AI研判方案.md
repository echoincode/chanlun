# 收盘分型 AI 研判方案设计（重新设计版）__废弃

> 本方案基于 **2026-09-07 对真实代码的实地探查** 重新设计，修正了旧版文档中已与代码脱节的假设，
> 并补充完整落地架构与**改造清单（§7）**。
>
> 相关背景：本项目已移除 tushare / baostock，统一为 **stockdb** 单一数据源；定时调度已删除，
> 监控改为 **Web 页面「🚀 立即执行收盘监控」手动触发**；交易日历已接入 `stock_sdk.get_trade_days`
> 增量补齐；股票名接口 `get_stock_name`（stock_names.py:69）**已可用**（`items` 已带 `name`），
> 但行业/板块/估值等基础信息仍待接入（首版 AI 不传，见 §3.3/§6.3）。
> 前端绘图 SDK（gp/bk/zb/tu.js）接口见 `docs/Ai.md`，本方案不涉及前端绘图。
>
> **修订记录**：2026-09-08 经《审核报告》复核，采纳 P0/P1/P2 全部修正（凭据轮换、输出预算、`AI_MAX_SIGNALS`、超时/重试、依赖与 tests 入库位置等），详见 §11。

---

## 1. 现状与变更（相对旧版文档）

| 旧版假设 | 真实代码（探查结论） | 本方案处理 |
|---|---|---|
| `_extract_segments` 仅含索引字段，须在 `build_ai_payload` 反查价格 | `runner.py:175-176` 已注入 `start_price`/`end_price` | 直接采用 segments 自带价格；反查仅作兜底（§3.2） |
| `run_monitor` 需改造才能传出 `summary`/`df`（§4.2「必改项」） | `monitor_job.py:289-315` **已实现** `items`，每条含 `summary`/`df_window`/`current_rec`/`last_rec`/`is_new` | 列为「已完成」，AI 层在其后插入（§6.2） |
| `settings` 已有 `AI_*` 配置 | `settings.py` **无任何 `AI_*`**（需新建） | 列为改造第一步（§7 Step 1） |
| `build_ai_payload`/`call_ai`/`parse_review` 待新建 | 仅 `tests/test_ai_payload.py` 有 `build_ai_payload` 原型；`tests/test_ai_api.py` 有 OpenAI 连通测试；生产无 | 提升原型为正式实现（§7 Step 2/3），正式单测迁至 `src/ai/tests/`（§7 Step 5/6） |

**结论**：数据通道（`items`）与测试原型已就绪，真正待建的是 `AI_*` 配置、正式 `src/ai/` 模块、与 `run_monitor` / Web 的集成。

---

## 2. 设计目标与原则

- **目标**：在「收盘分型监控」手动触发后，把筛选出的**新分型标的**连同缠论结构与行情，交给大模型，输出
  **可信性结论、风险点、操作建议、需人工复核项**，并合并进推送卡片。
- **原则**：
  1. **够用即可、可控成本、可解释**：只传与本次分型判断相关且 AI 看得懂的数据，聚合 1 次请求。
  2. **降级优先**：AI 不可用 / 关闭 / 失败时，**只推原「新分型」事实卡片**，不影响主流程。
  3. **不泄密、可轮换**：API Key 仅从环境变量读取，不落源码、不打印；历史泄露的 Key 必须作废轮换（§8）。
  4. **可测试**：payload 组装可在无 Key 环境下单测；API 调用单独连通测试（单测随正式代码入库于 `src/ai/tests/`）。

---

## 3. 传给 AI 的数据

### 3.1 必传：新分型与上下文（来自 `run_monitor` 的 `items`）

`items` 元素当前结构（`monitor_job.py:289-315`）：
```python
{
  "code": "600588.SH",
  "name": "用友网络",                 # get_stock_name(code) 已可用
  "is_new": True,                     # 当日形成且相较快照为新
  "current_rec": {"type": "top", "datetime": "2026-08-25", "price": 12.45},
  "last_rec": {...},                  # state 去重快照（仅去重用）
  "summary": {                        # analyze() 全量 summary
      "fractals": [{index, type, high, low, datetime}, ...],
      "segments": [{start_idx, end_idx, start_type, end_type, direction,
                    start_price, end_price}, ...]   # ★ 已含价格
  },
  "df_window": [ {date, open, high, low, close, volume, amount}, ... ]  # 近 60 根日线
}
```

| 字段 | 来源 | AI 用途 |
|------|------|---------|
| `code` / `name` | `items` | 定位 / 展示 |
| `new_fractal` | `current_rec`（`type`/`datetime`/`price`） | 本次分型锚点（顶=high，底=low） |
| `prev_fractal` | `summary.fractals` 中 datetime 早于 `current_rec` 的最近一个 | 节奏研判（≠ 去重快照 `last_rec`） |
| `recent_fractals` | `summary.fractals` 切片（近 5~8） | 分型排列 / 包含关系 |
| `recent_segments` | `summary.segments` 切片（近 3~5） | 上升/下降笔、笔破坏 |
| `kline_window` | `df_window` 切片（近 30 根） | 分型当日量价、趋势 |
| `last_close` | `df_window[-1].close` | 与分型价位对比 |

### 3.2 切片与价格（修正旧版反查假设）

1. 过滤 `items` 中 `is_new=True`。
2. `recent_fractals` = `summary.fractals` **最后 8 个**；`recent_segments` = `summary.segments` **最后 5 笔**。
3. **价格直接采用 `segment.start_price`/`end_price`**（已在 `runner.py:175-176` 注入）。
   仅当某笔缺失价格时，用 `start_idx`/`end_idx` 到 `df_window` 反查 `close/high/low` 兜底（`tests/test_ai_payload.py:44-55` 同逻辑）。
4. **`new_fractal` 一律取 `current_rec`**；`prev_fractal` 取 `summary.fractals` 中 datetime **早于** `current_rec` 的最近一个
   （而非简单取 `recent_fractals` 倒数第 2，避免分型列表末位非「本次分型」时错位）。
5. `kline_window` 取 `df_window` 最后 `AI_KLINE_WINDOW`（默认 30，硬上限 60）根。

> 一致性注意：`monitor_job._build_card` 取 `fractals[-2:]`（全量末 2，不受回看窗口约束），
> 而 `_pick_latest_fractal` 取窗口内最新。AI 研判按 §3.2 的「切片」口径即可，无需复用两者差异。

### 3.3 不传：标的基础信息（基本面）

**本项目不做基本面研判**，不传行业/板块/市值/PE/PB 等基础信息，
`settings` 中亦**无** `AI_INCLUDE_FUNDAMENTALS` 开关（已移除）。
理由：本工具定位为纯缠论量价 + 资金流的技术研判，基本面不参与分型可信度判断；
且 stockdb 行业/板块/估值接口（`bk`/`zb`）可用性未确认。
提示词中已明确要求模型**不得编造**基本面/宏观/新闻等未提供信息。

> **资金流（已落地，无开关）**：个股日资金流（stockdb 资金流表 `rd.get('资金流', code, date)`）已在
> 单标的悬浮分支实现，**默认必须发送、不提供开关**，作为分型量价配合的增强维度，
> 内嵌进 `kline_window` 每根记录的 `flow` 字段（主力/超大/大/中/小单净流入及买卖额）；
> 只查询「最新分型当日及其之后」的交易日，取数失败仅记 WARN，不阻断主流程。
> 批量分支可复用同一 `StockDBFetcher.fetch_money_flow`，`meta.include_money_flow` 标记是否附带。

### 3.4 不传

- 全量历史 K 线、原始 `result_df`、整个 `summary`（仅传 dict 化片段）。
- 任何密钥 / token / 内部配置。

---

## 4. 输入结构与提示词

### 4.1 输入 JSON 模板

请求体 = `meta` + `context` + `signals`（一只标的一个条目，聚合发送）。
`meta.truncated=true` 时表示仅取前 N 只研判（超 `AI_MAX_SIGNALS` 截断），推送导语须明示
「本期仅研判前 N 只」（见 §5.3）。

```json
{
  "meta": {
    "task": "收盘分型可信性研判",
    "monitor_date": "2026-08-25",
    "trigger": "手动触发",
    "data_source": "stockdb",
    "lookback_days": 120,
    "new_signal_count": 2,
    "truncated": false
  },
  "context": {
    "market_note": "A股日线，前复权；分型基于缠论标准定义；仅供辅助，不构成投资建议",
    "field_glossary": {
      "fractal_type": "top=顶分型(可能回调), bottom=底分型(可能反弹)",
      "segments.direction": "up=上升笔, down=下降笔",
      "kline_window": "近30根日线，date/open/high/low/close/volume/amount"
    }
  },
  "signals": [
    {
      "code": "600588.SH",
      "name": "用友网络",
      "new_fractal": {"type": "top", "date": "2026-08-25", "price": 12.45},
      "prev_fractal": {"type": "bottom", "date": "2026-08-06", "price": 10.80},
      "recent_fractals": [
        {"index": 10, "type": "bottom", "datetime": "2026-08-06", "high": 10.9, "low": 10.8},
        {"index": 25, "type": "top",    "datetime": "2026-08-25", "high": 12.5, "low": 12.4}
      ],
      "recent_segments": [
        {"direction": "up", "start_idx": 10, "end_idx": 25, "start_type": "bottom",
         "end_type": "top", "start_price": 10.8, "end_price": 12.45}
      ],
      "kline_window": [
        {"date": "2026-08-25", "open": 12.1, "high": 12.5, "low": 12.0, "close": 12.45, "volume": 1234567, "amount": 1.5e8}
      ],
      "last_close": 12.45,
      "extra": {}
    }
  ]
}
```

### 4.2 提示词（system / user）

```
你是 A 股缠论分析的辅助研判助手。下面是某日收盘后监控到的"新分型"标的，
已附带其缠论结构(分型/笔序列)与近期日线行情。请结合以下信息研判：

1) 该分型是否"标准/可信"（是否含包含关系未处理、是否笔破坏、量价是否配合）；
2) 当前处于上升笔还是下降笔、与上一分型节奏是否连贯；
3) 给出风险点与可操作建议；
4) 标注"需人工复核"的存疑项（如数据缺口、分型定义边界模糊）。

注意：
- 仅基于所给数据，不要编造行情；
- 严格只输出 JSON（不要解释、不要 markdown 代码围栏），
  schema 见调用方约定（例：{"reviews":[{"code":...,"credibility":...,"credibility_reason":...,"risk_points":[...],"suggestion":...,"need_human_review":[...]}],"summary":...}）；
- 区分"高可信/中可信/低可信"，并说明依据；
- 投资建议须标注"仅供参考，非买卖依据"。
```

---

## 5. 回答模板与推送整合

### 5.1 回答 JSON 模板（程序解析 + 推送）

```json
{
  "generated_at": "2026-08-25T16:35:00",
  "reviews": [
    {
      "code": "600588.SH",
      "name": "用友网络",
      "fractal_type": "top",
      "fractal_date": "2026-08-25",
      "credibility": "中可信",
      "credibility_reason": "分型形态标准，但量能未明显放大，处上升笔末端，假突破概率中等",
      "risk_points": ["板块未同步走弱，单独顶分型信号偏弱", "近30日振幅偏大，止损位难设"],
      "suggestion": "已持仓可观望至收盘确认；未持仓不追高，等回踩不破前低再评估（仅供参考，非买卖依据）",
      "need_human_review": ["当日为复牌/公告日，分时异常可能影响分型有效性"]
    }
  ],
  "summary": "本期 2 只新分型：1 只顶分型(中可信)、1 只底分型(高可信)；整体偏震荡，无强趋势信号"
}
```

### 5.2 字段说明

| 字段 | 取值 | 说明 |
|------|------|------|
| `credibility` | 高 / 中 / 低 | 分型有效性整体判断（与提示词、前端徽章口径一致；旧文档曾写「高可信/中可信/低可信」，已统一为「高/中/低」） |
| `credibility_reason` | 自然语言 | 形态标准度、量价配合、笔结构、资金流配合 |
| `risk_points` | list[str] | 主要风险 / 反例 |
| `suggestion` | 自然语言 | 操作建议，**须含免责声明** |
| `need_human_review` | list[str] | 存疑项，需人工确认 |

> **解析约束（防幻觉）**：`parse_review` 须校验每个 `reviews[].code` 均在请求 `signals` 的 code 集合内，
> 越界/伪造条目丢弃并告警（实现见 §6.1）。

### 5.3 推送整合

- 原 `monitor_job` 卡片（事实层）保留；
- AI `reviews` 作为「研判层」追加在每只标的卡片之后；
- 顶部 `summary` 作为消息导语；若 `meta.truncated=true`，导语追加「本期仅研判前 N 只」。
- **推送长度控制**：每只标的研判文本（credibility_reason + risk_points + suggestion）入卡片前
  **截断至 ≤200 字**（此前企微卡片已触发字数限制需切片），全文仅在 Web 页展示。
- `run_monitor` 返回值新增 `ai_reviews` 键（见 §6.2），供 `web/app.py` 渲染与 `notify` 推送。

---

## 6. 落地架构

### 6.1 新增模块 `src/ai/`

```
src/ai/
  __init__.py        # 导出 build_ai_payload / call_ai / parse_review
  review.py          # 核心实现
  client.py          # OpenAI 兼容 / Ollama HTTP 客户端封装（可选拆分）
  tests/             # 正式单测（随代码入库；tests/ 旧目录已整体移出版本控制）
```

- `build_ai_payload(items) -> dict`：消费 `items`，按 §3.2 切片组装 §4.1 JSON（不传基本面，见 §3.3）；
  超 `AI_MAX_SIGNALS` 截断并置 `meta.truncated=true`；**`signals` 为空（无新分型）时直接返回空 dict，不调用 AI（省 token）**。
  可直接复用 `tests/test_ai_payload.py:58` 原型。
- `call_ai(payload) -> str`：调用大模型（OpenAI 兼容 / 本地 Ollama），含重试（≤`AI_MAX_RETRY`）与退避；
  请求强制 `response_format={"type":"json_object"}`（联通测试已验证服务端支持）并要求严格输出 §5.1 JSON；
  失败抛异常由上层降级。
- `parse_review(resp) -> dict`：校验并解析 JSON；处理非法 JSON、缺字段、`reviews` 为空等分支；
  **校验每个 `reviews[].code` ∈ 请求 `signals` 的 code 集合，越界/伪造条目丢弃并 `logger.warning`**（防幻觉）。

### 6.2 `run_monitor` 集成点（已完成数据通道，仅需加调用）

`monitor_job.py:289-315` 已组装 `items`；在其后、推送前插入：

```python
from src.ai.review import build_ai_payload, call_ai, parse_review

ai_reviews = []
if settings.AI_ENABLED:
    try:
        # 内部已处理「无新分型即返回空」；非 JSON / 超时 / 非 2xx 由 call_ai 抛异常
        payload = build_ai_payload(items)
        if payload.get("signals"):
            resp = call_ai(payload)
            ai_reviews = parse_review(resp).get("reviews", [])
        else:
            ai_reviews = []   # 无新分型，跳过 AI，不耗 token
    except Exception as e:
        logger.error("AI 研判失败，降级为仅事实卡片: %s", e)
# 把 ai_reviews 并入卡片 / messages，并在返回 dict 增加 "ai_reviews": ai_reviews
```

返回值在现有 `{"ran","skipped_reason","scanned","new_fractal","cards","messages","items"}`
基础上**新增 `"ai_reviews": list[dict]`**。

### 6.3 配置项（`settings.py` 新增，仅环境变量读取）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `AI_ENABLED` | `False` | 总开关，False 时跳过 AI 层 |
| `AI_BASE_URL` | 空 | 云端 API 地址；Ollama 填 `http://host.docker.internal:11434/v1`（Docker/WSL2 部署）或 `http://localhost:11434/v1`（宿主机直跑） |
| `AI_MODEL` | 空 | 模型名 |
| `AI_API_KEY` | **环境变量** | 见 §8 安全约束与凭据轮换 |
| `AI_TIMEOUT` | `60` | 单次请求超时（秒），大 payload（≤8 标的）建议 ≥60 |
| `AI_MAX_TOKENS` | `4000` | 回答上限，须 > 单只 review×标的数，避免 JSON 被截断（见 §6.5） |
| `AI_MAX_RETRY` | `1` | 失败重试次数（退避 2s） |
| `AI_KLINE_WINDOW` | `30` | 每条标传入日线根数（硬上限 60） |
| `AI_MAX_SIGNALS` | `8` | 单请求最大标的数，超出截断（按优先级取前 N，置 `meta.truncated=true`） |

> **输出预算提示**：8 标的 × 每标 review（≈500-800 tokens）≈ 4-6k 输出 tokens，`AI_MAX_TOKENS=4000`
> 配合 `AI_MAX_SIGNALS=8` 基本覆盖；若确需更多标的，应改为**按标的分批请求**（第二轮）。

### 6.4 Web 集成（`web/app.py`）

「🚀 立即执行收盘监控」回调 `run_monitor(force=True)` 已就位（行 329），渲染分支（行 330-345）
新增对 `res.get("ai_reviews", [])` 的展示（研判层卡片），并在页面顶部显示 `meta.summary` 导语。
**触发期间显示「AI 研判中…」状态提示，避免用户误判卡死**（AI 层最坏阻塞约 60-90s，见 §6.5）。
可选：加 `AI_ENABLED` 状态徽标。

### 6.5 重试、限流与降级

- 重试：`call_ai` 失败（网络/超时/非 2xx）重试最多 `AI_MAX_RETRY=1` 次，退避 2s，不再叠加多层。
- **总时长预算**：AI 层（含 1 次重试）整体上限 **≤90s**，超出直接降级（Web 同步触发，避免 UI 长时间转圈）。
- 失败告警：连续失败 `logger.error`，避免静默丢研判。
- 降级：`AI_ENABLED=False` 或最终失败 → 仅推原「新分型」卡片，不影响主流程。
- 成本：每周期聚合 1 次请求；`AI_MAX_SIGNALS=8` / `AI_KLINE_WINDOW=30` / `AI_MAX_TOKENS=4000` 已限上限，
  避免输出截断导致 `parse_review` 失败进而全部降级。

### 6.6 结果缓存与重复研判防护（首版落地）

按 `(code, fractal_date, fractal_type)` 缓存 AI 结果，避免行情异动日（或用户反复点击「立即执行」）
重复调用烧钱。**首版即实现极简版**：在 state 中记录当日已研判标记，命中则跳过（约几行代码）；
完整的跨进程/跨日缓存列入第二轮。

---

## 7. 改造清单（实施步骤）

> 本清单为落地执行顺序，每步给出文件、改动与验证方法。

| # | 文件 | 改动 | 验证 |
|---|------|------|------|
| **1** | `src/config/settings.py` | 新增 §6.3 的 10 个 `AI_*` 配置（含 `AI_MAX_RETRY`；仅 `os.environ.get`，Key 不落地） | `python -c "import src.config.settings"` 无报错；`settings.AI_ENABLED is False` |
| **2** | `src/ai/__init__.py` | 新建包，导出 `build_ai_payload` / `call_ai` / `parse_review` | 导入成功 |
| **3** | `src/ai/review.py` + `requirements.txt` | 实现三函数；`build_ai_payload` 复用 `tests/test_ai_payload.py:58` 原型并修正 segments 用自带价格、`signals` 空跳过；`call_ai` 强制 `response_format=json_object` 并支持 OpenAI 兼容 + Ollama（免 key）；`parse_review` 健壮解析 + code 校验；**`requirements.txt` 增加 `openai>=1.x`** | `pytest src/ai/tests/` 通过 |
| **4** | `scripts/monitor_job.py` | 在 `items` 组装后、推送前插入 AI 层调用（§6.2，含空 signals 跳过）；返回 dict 新增 `ai_reviews` 键；并入卡片 / messages；state 记当日已研判（§6.6） | 手动触发后 `res["ai_reviews"]` 为 list；`AI_ENABLED=False` 时为空；无新分型日不调用 AI |
| **5** | `src/ai/tests/test_payload.py` | 由旧 `tests/test_ai_payload.py` 提升为对接正式 `src.ai.review.build_ai_payload`，并随正式代码入库；补 `parse_review` 分支测试（非法 JSON / 缺字段 / `reviews` 为空 / 越界 code） | `pytest` 全绿 |
| **6** | `src/ai/tests/test_api.py` | 重写旧 `tests/test_ai_api.py`：key/base_url/model 全部 `os.environ.get(...)`，`AI_API_KEY` 缺失时 `unittest.skip`；**清除一切硬编码凭据**（§8 凭据轮换前置） | 有 key 时跑通；无 key 时跳过 |
| **7** | `web/app.py` | 「🚀 立即执行收盘监控」渲染分支展示 `ai_reviews`；顶部显示 `summary` 导语；加「AI 研判中…」提示；可选 `AI_ENABLED` 徽标 | 页面点击后展示研判层卡片；`HEALTH=200` |
| **8** | `.env.example` / `docker-compose.yml` / `requirements.txt` | 补充 `AI_*` 环境变量（web / cli 服务），`AI_API_KEY` 走 secret / `.env`；确认 `requirements.txt` 含 `openai>=1.x` | `docker compose config` 含 `AI_ENABLED` 等；不出现明文 key |
| **9** | `README.md` | 新增「AI 研判」小节：开关、配置、降级说明、接入方式（云端/Ollama）、**凭据泄露应急轮换** | 文档审阅通过 |

**依赖顺序**：1 → 2/3 → 4 → 7（前端）→ 8/9（配置与文档）；5/6 单测随 3 同步，并入库于 `src/ai/tests/`。

**不改动**：`runner.py` 的 `analyze`/`_extract_segments`（已满足需求）、`monitor_job` 的 `items` 数据结构（已就绪）、
`trade_calendar` / `stock_names`（与本方案解耦，股票名已可用，行业/估值待接口不影响首版）。

---

## 8. 安全约束

- `AI_API_KEY` **仅从环境变量读取**（`.env` / docker-compose / 宿主机 env），禁止写入 `settings.py` 源码、禁止打印/写入日志。
- **凭据泄露应急处置**：若任何历史提交/文件中曾出现真实 Key（即便已从工作区删除），**唯一有效补救是到服务商处作废并轮换该 Key**；
  文件级删除或 `.gitignore` 无法清除已推送的 git 历史，历史中凭据视为永久泄露。
- 本地 Ollama 模式（`AI_BASE_URL` 指向 `host.docker.internal:11434` 或本机 `11434`）无需 key；`call_ai` 检测本机地址则跳过 key 校验。
- `AI_BASE_URL` / `AI_MODEL` / `AI_API_KEY` 进入镜像前确认已在 `.dockerignore` / 构建层排除，避免泄露。

---

## 9. 验证计划

1. **单元测试**（无 Key 可跑）：`pytest src/ai/tests/test_payload.py` —— 断言 `recent_fractals≤8`、`recent_segments≤5`、
   `kline_window≤AI_KLINE_WINDOW`、segments 直接采用 `start_price`/`end_price`；`parse_review` 处理非法 JSON / 缺 `credibility` / `reviews` 为空 / 越界 code。
2. **联通测试**：有 `AI_API_KEY` 时 `pytest src/ai/tests/test_api.py` 跑通；无 key 时自动 `skip`。
3. **集成验证**：`python -c "from scripts.monitor_job import run_monitor; import json; print(json.dumps(run_monitor(force=True).get('ai_reviews'), ensure_ascii=False)[:500])"`
   - `AI_ENABLED=False` → `ai_reviews=[]`，主流程不报错；
   - 无新分型日 → 不调用 AI，`ai_reviews=[]`；
   - `AI_ENABLED=True` + 有效 key → 返回研判列表，并合入推送卡片。
4. **Web**：`streamlit run web/app.py`，点「🚀 立即执行收盘监控」，确认研判层卡片渲染、`AI 研判中…` 提示、`HEALTH=200`。
5. **截断场景**：模拟 8+ 标的 payload 跑 `parse_review`，确认 `meta.truncated` 行为与降级不崩。

---

## 10. 待确认 / 开放问题

- **AI 接入方式**：云端 API（需 key）还是本地 Ollama（免 key、隐私好）？两者 `call_ai` 都支持，默认由 `AI_BASE_URL` 决定。
- **基础信息**：已明确**不传基本面**（§3.3），`AI_INCLUDE_FUNDAMENTALS` 配置项已移除，无待确认项。
- **回答分级**：当前通用版；是否需支持「多空分级」或「持仓/空仓」分场景建议，第二轮迭代。
- **结果缓存（§6.6）** 完整版列入第二轮，首版落地极简当日去重。

---

## 11. 审核修订记录（2026-09-08）

依据《收盘分型 AI 研判方案审核报告》采纳以下修正：

- **P0-1 凭据安全**：§8 新增「凭据泄露应急处置」（历史泄露 Key 必须作废轮换）；§7 Step 6 改为重写并清除硬编码凭据、入库于 `src/ai/tests/`。
- **P1-1 输出预算**：`AI_MAX_SIGNALS` 20→**8**、`AI_MAX_TOKENS` 1500→**4000**（§6.3/§6.5）；`meta.truncated` 导语提示（§5.3）。
- **P1-2 超时/重试**：`AI_TIMEOUT` 30→**60**；新增 `AI_MAX_RETRY=1`（§6.3）；§6.5 明确定义总时长预算 ≤90s 与 Web 阻塞提示（§6.4）。
- **P2-1 依赖**：§7 Step 3/8 明确 `requirements.txt` 增加 `openai>=1.x`。
- **P2-2 空 signals**：`build_ai_payload` 空则跳过 AI（§6.1/§6.2）。
- **P2-3 推送长度**：§5.3 增加每标研判 ≤200 字截断策略。
- **P2-4 Ollama 地址**：§6.3 `AI_BASE_URL` 改为 `host.docker.internal:11434`（Docker/WSL2）。
- **P2-5 防幻觉**：`parse_review` 校验 `reviews[].code ∈ signals`（§5.2/§6.1）。
- **P2-6 tests 入库**：正式单测由 `tests/`（已移出版本控制）迁至 `src/ai/tests/`（§7 Step 5/6、§9）。
- **P2-7 重复研判**：§6.6 首版即落地当日去重标记。
- **P2-8 prev_fractal 口径**：§3.2 明确 `new_fractal=current_rec`、`prev_fractal` 取 datetime 早于 `current_rec` 的最近分型（§3.1 同步）。
- **断言 #9 过时**：背景与 §3.3 更新——`get_stock_name` 已可用，`items` 已带 `name`，仅行业/估值待接入。
