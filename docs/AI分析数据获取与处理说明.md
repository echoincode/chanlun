# AI 深度分析：发送给大模型的数据「怎么获取、怎么处理、受哪些约束」

> 适用代码：`web/app.py`（入口与弹窗、留存）、`src/ai/review.py`（payload 组装 / 调用 / 解析 / 系统提示词）
> 适用函数：`build_single_payload()`、`_compute_indicators()`、`_fetch_money_flow_map()`、`call_ai()`、`parse_review()`、`save_ai_analysis()`
> 配套文档：《收盘分型 AI 研判方案》（研判字段约定）、`docs/Ai.md`

本文档不局限于技术实现，还把**约束与契约**讲全：从数据获取、增强处理、组装发送，到系统提示词里对模型的研判规则、可信性评级标准、防幻觉约束、字段口径契约、输出契约与人工复核触发条件，覆盖整条链路。

---

## 1. 总览：数据从哪来到哪去

```
用户点「开始分析」
   └─ cached_analysis(stock_code, 起止日期, data_type, frequency, data_source)
         ├─ fetch_data(...)      # 取 K 线（StockDB 远程 / 本地缓存）
         └─ analyze(...)         # 缠论计算 → result(完整 K 线 DataFrame) + summary(分型/笔)
   └─ st.session_state.ai_ctx = {            # 存给悬浮按钮复用，rerun 安全
         kline_tail,   # 「最新分型当日」起、最多 AI_KLINE_WINDOW 根的尾窗切片
         full_result,  # 完整序列（本地算 MACD 等，必须够长才稳）
         summary, stock_code, stock_name, data_type, frequency, 起止日期
      }

用户点「🤖 AI 深度分析」(FAB)
   └─ _ai_dialog_body()                         # @st.dialog 弹窗
         └─ build_single_payload(              # ★ 核心：组装发送给 AI 的数据
               ctx["kline_tail"], ctx["summary"],
               stock_code, stock_name,
               data_type=..., frequency=...,
               full_series=ctx["full_result"])  # 完整序列 → 本地算指标
               └─ payload: { meta, context, signals[1] }
         └─ call_ai(payload)
               ├─ user_msg = 任务引导语 + json.dumps(payload)   # 弱模型也需要指令
               ├─ client.chat.completions.create(
               │     system = _SYSTEM_PROMPT, user = user_msg,
               │     response_format={"type":"json_object"},
               │     temperature=0.2, max_retry=AI_MAX_RETRY)
               └─ text
         └─ parse_review(text) → review dict   # 标准化、缺字段给默认
   └─ save_ai_analysis(code, payload, review, ctx)  # 落盘 output/ai_analysis/
```

**一句话**：发给 AI 的不是原始 K 线，而是经过「分型定位裁剪 + 多维增强字段挂载 + 结构化为 JSON」后的 `payload`；模型须**仅基于这份数据**、按系统提示词的研判规则与约束给出 JSON 研判；结果回传后标准化展示并存盘留存。

---

## 2. 上游：原始数据怎么获取

### 2.1 主分析取数（`web/app.py`）
- 用户选择 `stock_code / 起止日期 / data_type(daily|minute) / frequency / data_source` 后点「开始分析」。
- 调用 `cached_analysis()`：先查**本地缓存**，未命中再实时查 **StockDB**（`data_source` 默认 `stockdb`）。
- 产出两份核心对象：
  - `result`：`pandas.DataFrame`，**完整序列** K 线（`datetime/open/high/low/close/volume/amount`），带 `datetime` 列（日线形如 `"2026-09-03"`，分钟线带时分）。
  - `summary`：`analyze()` 返回的汇总 dict，含 `fractals`（分型列表）、`segments`（笔列表）、`fractal_count`、`segment_count` 等。

### 2.2 AI 上下文 `ai_ctx`（`web/app.py`）
分析成功后写入 `st.session_state.ai_ctx`，供悬浮按钮复用、rerun 安全：
- `kline_tail`：以**最新分型当日**为起点（用分型 `index` 标签 `.loc` 定位，抗 trimming 偏移），向后取 `AI_KLINE_WINDOW` 根；异常则退回 `result.tail(AI_KLINE_WINDOW)`。目的：让 AI 看到分型确认后的量价演化。
- `full_result`：即 `result` 完整序列，传给 `build_single_payload` 的 `full_series` 参数，用于本地计算 MACD（窗口仅 ~30 根不足以稳定 MACD，必须基于完整序列）。
- 其余：`summary / stock_code / stock_name / data_type / frequency / 起止日期`。

---

## 3. 核心：`build_single_payload()` 怎么处理数据

入口：`src/ai/review.py::build_single_payload(kline_tail, summary, stock_code, stock_name, data_type, frequency, full_series)`

返回结构（与《收盘分型 AI 研判方案》§4.1 一致）：`{ meta, context, signals[1] }`。

### 3.1 前置：无分型直接跳过
```python
if not fractals:
    return {}   # 调用方据此跳过 AI，省 token
```
`summary` 里没有分型 → 返回空 dict，弹窗提示「未识别到分型，无需 AI 研判」。

### 3.2 窗口裁剪与日期归一化
```python
kline_window = _kline_to_records(kline_tail)[: settings.AI_KLINE_WINDOW]
last_close   = kline_window[-1]["close"]
```
- `_kline_to_records()` 把尾窗 DataFrame 转成记录列表，并**归一化日期**：
  - 日线（无时分）→ `"20260903"`（8 位无横杠）
  - 分钟线（含时分）→ `"20260913140000"`（14 位）
- 每条记录基础字段：`date / open / high / low / close / volume / amount`。

### 3.3 挂载的增强维度（"怎么处理"的重点）

各维度均遵循同一容错约束（详见 §6.4）：**任一环节异常 → 捕获并降级（仅记日志/警告），绝不阻断 payload 组装**。

| 维度 | 默认 | 数据源 | 处理方式 | 挂载位置 | 失败标志 |
|---|---|---|---|---|---|
| 资金流 | 必须（无开关） | `StockDBFetcher.fetch_money_flow` | 仅查「最新分型当日及其之后」交易日 | 每根 `flow`（主力/超大/大/中/小单净流入等） | `meta.include_money_flow=False` |
| 技术指标 | 必须（无开关，本地 pandas） | 本地 `full_series` 计算，零外部依赖 | MACD/RSI/BOLL/MA/量比/振幅，按日期映射 | 每根 `macd_hist/rsi/ma5…` + 窗口首根快照 `context.indicators` | `meta.include_indicators=False` |
| 换手率 | 仅日线 | `StockDBFetcher.fetch_quote_extra` | 经 rd.get_data 拉取 | 每根 `turnover` | `meta.include_turnover=False` |
| 融资融券 | 仅日线 | `StockDBFetcher.fetch_margin_trading` | 按窗口交易日区间查 | 每根 `margin` | `meta.include_margin=False` |
| 限售解禁 | 仅日线 | `StockDBFetcher.fetch_locked_shares` | 查「最后一根 K 线之后 30 个交易日」 | `context.upcoming_unlocks`（None=未查/失败，[]=查成功但无解禁） | `meta.include_unlock=False` |
| 基本面 | **不传** | — | 本项目不做基本面研判，config 无相关开关 | — | — |

#### 3.3.1 技术指标：`_compute_indicators(full_df)`
- 基于 `full_series`（完整序列，建议 ≥35 根以稳定 MACD）：
  - `ema12/ema26 → DIF`，`DIF 的 ema9 → DEA`，`MACD柱 = (DIF-DEA)*2`
  - `RSI(14)` Wilder 平滑；`BOLL(20)` 中轨±2σ；`MA5/MA10/MA20`
  - 量比 `vol/近5日均量`；振幅 `(high-low)/昨收*100`
- 输出 `{归一化日期: {macd_dif, macd_dea, macd_hist, rsi, boll_*, ma5/10/20, vol_ratio, amplitude}}`。
- 挂载：遍历 `kline_window`，用 `rec["date"]` 查 `ind_map`；命中则 `rec.update(...)`，并置 `_ind_attached=True`。
- **快照**：`context.indicators` = 窗口首根（最新分型当日）的完整指标 + 换手率，供 AI 判断 MACD 金叉/死叉/背离、RSI 超买超卖、价格相对 BOLL 轨道位置。

#### 3.3.2 资金流：`_fetch_money_flow_map(kline_records, code, fractal_day)`
- 从每条记录的 `date` 取前 8 位(YYYYMMDD) 去重，并按 `fractal_day` 过滤只保留分型当日及之后。
- 返回 `{date8: flow_dict}`；挂载时 `rec["flow"] = mf_map.get(date8)`，None 表示该日无数据。

### 3.4 组装 `meta / context / signals`
- **meta**：`data_type / frequency / truncated / include_money_flow / include_indicators / include_turnover / include_margin / include_unlock`。
  - `include_*` 现在**如实反映指标是否真的挂上了**（如 `_ind_attached or focus_ind is not None`），避免"标了已附带但数据缺失"的误导。
- **context**：`market_note`（A股前复权、缠论标准、仅供参考）、`field_glossary`（字段语义词典，单位/方向/0~1 比例等，统一以它为准）、`indicators`（快照）、`upcoming_unlocks`、`kline_window`、`last_close`。
- **signals[1]**：`{code, name, recent_fractals(最近2个), recent_segments(最近5笔)}`。

---

## 4. 发送：怎么交给大模型

`call_ai(payload)`（`src/ai/review.py`）：
1. 配置校验：`AI_ENABLED`、`AI_BASE_URL / AI_MODEL / AI_API_KEY` 齐全，否则抛明确错误（前端降级为 warning）。
2. `payload_str = json.dumps(payload, ensure_ascii=False)`。
3. `user_msg = "请依据系统提示词的要求，研判下面这只标的的缠论分型数据，并严格按约定的 JSON 字段输出结果（只输出 JSON，不要其他文字）：\n" + payload_str`
   - 加一句自然语言引导：弱模型（含本地小模型）需要明确指令才知道要做什么，不能只丢一个 JSON。
4. `client.chat.completions.create(...)`：`system=_SYSTEM_PROMPT`（缠论研判规则、可信性评级标准、防幻觉约束，见 §6.2/§6.3），`response_format={"type":"json_object"}`，`temperature=0.2`（稳定可复现，按约定不开放为配置项），带 `AI_MAX_RETRY` 重试。
5. 返回 `text`（模型原始 JSON 文本）。

---

## 5. 解析：AI 返回怎么处理

`parse_review(text)`（输出契约见 §6.5）：
- `json.loads(text)` 容错；非 dict / 解析失败 → 返回空 dict（不抛异常，避免前端 KeyError）。
- 标准化输出：`code / focus_fractal / credibility / credibility_reason / risk_points / suggestion / need_human_review`，缺字段给默认值。
- 弹窗中 **AI 返回结果显示在上方**（`_render_review`），**发送给大模型的内容在下方**（`_render_sent_content`，含逐项解释与完整 JSON 展开）。

---

## 6. 约束与契约（核心：不仅是技术细节）

整条链路受以下约束支配，任何改动都不得破坏它们。

### 6.1 输入数据口径契约（字段语义、单位、格式）

模型解读数据**一律以 `context.field_glossary` 为准**（系统提示词也明确这一点）。关键口径：

| 字段 | 含义 | 单位 / 格式 | 关键约束 |
|---|---|---|---|
| `recent_fractals[].type` | `top`=顶分型(可能回调)、`bottom`=底分型(可能反弹) | 枚举 | — |
| `recent_fractals[].datetime` | 分型生成时间 | **日线 YYYYMMDD(8位) / 分钟 YYYYMMDDHHMMSS(14位)** | 与 `kline_window[].date` 格式不同，但都在 glossary 声明 |
| `kline_window[].date` | K 线日期 | **日线 `20260903`(8位无横杠) / 分钟 `20260913140000`(14位)** | 由 `_kline_to_records` 归一化，所有增强字段据此挂载 |
| `kline_window[].volume` | 成交量 | **股** | — |
| `kline_window[].amount` | 成交额 | **元** | — |
| `kline_window[].turnover` | 换手率 | **%**（成交量/流通股本） | — |
| `kline_window[].vol_ratio` | 量比 = 当日量/近5日均量 | 标量，>1 放量、<1 缩量 | — |
| `kline_window[].amplitude` | 振幅 | **%**，`(高-低)/昨收*100` | — |
| `kline_window[].macd_hist` | MACD 柱 = (DIF-DEA)*2 | 标量，>0 多头、<0 空头，由负转正≈金叉、由正转负≈死叉 | **曾因日期键不符漏挂，见 §7.1** |
| `kline_window[].rsi` | RSI(14) | 标量，>70 超买、<30 超卖 | — |
| `kline_window[].flow` | 当日资金流 | **元**；`main_net` 正=流入/负=流出；`null`=当日无数据 | 含超大/大/中/小单、主力/散户买卖额 |
| `kline_window[].margin` | 当日融资融券 | **元**；`fin_value`=融资余额、`fin_buy_value`=融资买入额、`fin_sec_value`=两融余额、`sec_value`=融券余量 | 融资余额升/融资买入放大=杠杆看多 |
| `context.indicators` | 「最新分型当日」指标快照 | 含 `macd_dif/dea/hist`、`rsi`、`boll_*`、`ma5/10/20`、`vol_ratio`、`amplitude`、`turnover` | 与 `kline_window[0]` 对齐 |
| `context.upcoming_unlocks[]` | 未来 N 交易日限售解禁 | `day`(解禁日)、`num`(股数)、`rate1`(占总股本)、`rate2`(占流通股本) | **`rate1/rate2` 是 0~1 小数（0.7077=70.77%），非百分数**；`rate2>0.05`(占流通 5%+)即明显抛压 |
| `segments[].direction` | `up`=上升笔、`down`=下降笔 | 枚举 | — |

### 6.2 系统提示词研判规则（可信性评级标准）

`src/ai/review.py::_SYSTEM_PROMPT` 规定模型**必须明确给出 高/中/低，不得一律给「中」**。评级标准（全量）：

- **高**：分型形态标准成立，**且**具备——
  - 量价确认（分型后未破位、放量配合 `vol_ratio>1` 或换手率放大）；
  - MACD 同向（底分型金叉/底背离、顶分型死叉/顶背离）；
  - 资金流同向（底分型主力净流入 / 顶分型主力净流出）；
  - 融资余额趋势同向（底分型升/买入放大、顶分型降）；
  - 与当前笔或更大级别结构同向；
  - 近期无大额解禁（`upcoming_unlocks` 无 `rate2>0.05`）。
- **中**：分型形态成立，但**缺一项确认**——量能未明显放大(`vol_ratio≈1`/换手平淡) / MACD 未明显金叉背离 / 资金流方向不明或与分型反向力度弱 / 融资余额走平无倾向 / 笔结构既未被破坏也未强化 / 无更大级别印证。
- **低**：分型孤立、处于笔中段、量价背离、资金流明显反向、MACD 明显反向(顶分型却金叉) / 处于重要阻支撑位却未确认突破 / 或未来 N 日有 `rate2>0.05` 解禁形成供给抛压。
- **强制约束**：若 `upcoming_unlocks` 存在 `rate2>0.05` 的解禁，**必须**列入 `risk_points` 并据此下调底分型可信度（至少降一档）。

### 6.3 防幻觉与输出约束（模型侧严格约束）

系统提示词"严格约束（防幻觉，必须遵守）"：
1. **仅基于所给数据研判**，不得编造或臆测未提供的信息（宏观、基本面、新闻、财报等）。
2. **仅在确实缺失关键信息**（窗口过短无法确认分型、关键交易日无资金流）时，才如实说明「数据不足」并列入 `need_human_review`；若已有量价与资金流足以支撑判断，**必须给出明确 高/中/低，不得回避到「中」**。
3. **每条结论都要能追溯到所给数据中的具体依据**。
4. **金额单位换算（重要，曾出现 10 倍误读）**：所有 `flow`/`margin` 字段单位均**为「元」**。换算「亿」需 ÷1e8、换算「万」需 ÷1e4；严禁把元直接当「亿」（如 `558049274` 元 = `5.58` 亿，不是 `55.8` 亿）。凡引用融资金额、主力净流入、成交额等，必须先换算再写结论，并保留正确量级（优先用「亿/万」表述）。

此外：
- `signals` 未指定单一锚点分型，模型须**基于 `recent_fractals` 自行判断当前最值得关注的分型**，填入 `focus_fractal`（含 `datetime`/`type`/`reason`）。
- 必须**只输出一个 JSON 对象**，不要额外文字、不要 markdown 代码围栏。

### 6.4 容错 / 降级约束（发送侧）

- **增强维度互不阻断**：资金流 / 技术指标 / 换手率 / 融资融券 / 限售解禁 任一项取数或计算异常，均 `try/except` 捕获、仅记 `warning`，不影响其余字段与整体研判。
- **`meta.include_*` 如实反映**：取值 = 该维度是否真的挂到了数据上（如技术指标 `_ind_attached or focus_ind is not None`），**杜绝"标了已附带却数据缺失"**。
- **空值语义**：`flow=null`=当日无资金流；`upcoming_unlocks=[]`=已查且近期无解禁（区别于 `None`=未查/失败）；`context.indicators` 缺某字段 = 该指标未算出。
- **无分型跳过**：`summary` 无分型 → payload 返回 `{}`，前端提示无需研判，省 token。
- **降级幅度受控**：单维度失败最多导致对应 `include_*=False` 与该项数据缺失，不会让整个 `payload` 为空或报错。

### 6.5 输出契约（返回 JSON 字段与默认值）

`parse_review` 标准化字段（缺字段给默认，保证前端不 KeyError）：

| 字段 | 类型 | 说明 | 默认值 |
|---|---|---|---|
| `code` | str | 标的代码（与输入一致） | `""` |
| `focus_fractal` | dict | `{datetime, type, reason}` 模型自锁定的关注分型 | `{}` |
| `credibility` | str | `高/中/低` | `"未知"` |
| `credibility_reason` | str | 命中/缺失的确认项、对应哪一级 | `""` |
| `risk_points` | list[str] | 风险点 | `[]` |
| `suggestion` | str | 操作建议（仅供参考，非买卖依据） | `""` |
| `need_human_review` | list[str] | 需人工复核项 | `[]` |

### 6.6 需人工复核的触发条件

`need_human_review` 应填入（由模型判断，前端高亮）：
- 窗口过短 / 关键交易日无资金流，不足以确认分型；
- 缺失关键指标（如 MACD 字段缺失，无法判断背离/死叉）；
- 数据口径存疑（如某日资金流方向与价格走势明显矛盾，需核实数据源）；
- 出现 `rate2>0.05` 解禁但模型对其量级把握不确定时，建议人工复核比例影响。

---

## 7. 留存：结果落盘

`save_ai_analysis(stock_code, payload, review, ctx)`（`src/ai/review.py`，由 `web/app.py` 在分析完成后调用）：
- 目录：`项目根/output/ai_analysis/`（`os.makedirs(exist_ok=True)` 懒创建）。
- 文件：`{code}_{YYYYMMDD_HHMMSS}.json`，同时含 `sent_payload`（发送内容）与 `review`（返回结果），外加 `saved_at/stock_code/stock_name/data_type/frequency` 元数据。
- 约束：**任何写盘异常均捕获并 `warning`，绝不阻断主研判流程**；仅在一次「新分析」（`ai_dialog_payload` 未缓存）时落盘，重复打开已分析弹窗不重复写文件。

---

## 8. 已知问题与修复记录

### 8.1 MACD 算出来了却没附上（影响所有股票）
- **现象**：弹窗 `meta.include_indicators=True`（显示"技术指标：已附带"），但 AI 实际收到的 `kline_window` 里没有 `macd_hist`，`context.indicators` 为 null，导致 AI 无法判断背离。
- **根因**：`kline_window` 的 `date` 已归一化为无横杠（`"20260903"`），而 `_compute_indicators` 生成 `ind_map` 用键 `str(full_series["datetime"])`（带横杠 `"2026-09-03"`）。键格式不一致 → 挂载循环 `ind_map.get(rec["date"])` 取不到值 → 指标算出来没挂上。
- **修复**：
  1. 新增 `_normalize_dt_key(dt)`，与 `_kline_to_records` 完全一致口径（日线 8 位、分钟 14 位；字符串剔分隔符取数字）。
  2. `ind_map` 键改用 `_normalize_dt_key`。
  3. `include_indicators` 改为如实反映是否真挂载（`_ind_attached or focus_ind is not None`）。
- **验证**：旧 `str("2026-09-03")=="20260903"` → `False`（bug 确凿）；新 `_normalize_dt_key("2026-09-03")=="20260903"` → `True`（日线、分钟线均通过）。

### 8.2 融资余额被读大 10 倍
- **现象**：`fin_value=558049274` 元被模型解读为 `55.8 亿`（正确为 `5.58 亿`）。
- **根因**：模型未按单位换算（元 → 亿需 ÷1e8）。
- **修复**：在 `_SYSTEM_PROMPT` 严格约束新增第 4 条"金额单位换算"，并附实例，要求报告前先换算、用「亿/万」表述。

---

## 9. 排查清单（小结）

当发现"显示已附带但 AI 说没收到"或评级异常时：
1. **`meta.include_x` 是 True 还是 False？** False = 取数/计算失败（查日志 `warning`/`技术指标计算失败`/`资金流获取失败`）。
2. **True 但数据缺失？** 多为**日期键对齐**问题（`ind_map` 与各记录 `date` 口径不一致，`§8.1`），盯 `ind_map.get(rec["date"])` 是否命中。
3. **资金流/换手率/融资融券/解禁为空？** 增强维度可能本就无数据（`flow=null`、`include_margin=False`）或标的非两融，属正常降级，不阻断研判。
4. **评级与预期不符？** 核对 `§6.2` 标准，确认是否触发"缺一项确认→中"或"解禁→降档"；再查 `§6.1` 口径（尤其 `rate1/rate2` 是 0~1 小数、`flow/margin` 单位元需换算）。
5. **模型结论无依据 / 出现未提供信息？** 属违反 `§6.3` 防幻觉约束，应反馈到提示词或换模型。
