# 收盘分型 AI 单标的深度分析方案（悬浮按钮版）

> 本方案在 **Web 单标的分析页** 上新增一个「🤖 AI 深度分析」**悬浮按钮（FAB）**。
> 用户先点「🚀 开始分析」取得数据（既有流程不变），再点悬浮按钮，
> 即可把**已分析的 `result`/`summary`** 直接交给大模型研判并展示结果。
>
> **定位**：本方案是《收盘分型 AI 研判方案》的**单标的按需分支**，仅复用其 `src/ai` 的
> `call_ai`/`parse_review` 与 `AI_*` 配置；**不改动**现有分析/绘图/收盘监控批量推送逻辑。
>
> **探查基准**：`web/app.py`、`src/cli/runner.py`、`src/core/chanlun_processor.py`、
> `web/styles.py`（2026-09-08 代码状态）。
>
> **修订记录**：2026-09-08 初版；同日依评审问答修订——锚点分型改为「传最近分型序列由 AI 综合判断」、
> FAB 常驻可见（未分析/AI 关闭时点击给引导）、每次点击实时调用 AI（不做结果缓存）、
> 修复 FAB 渲染位置（移出分析分支，保证 rerun 后仍可触发）与 `ai_ctx` 赋值条件矛盾；
> 并补充 AI 接口参考（`tests/test_ai_api.py`）与「`base_url`/`token`/`model` 从 `.env` 读取」约束（含 `.env` 示例）。

---

## 1. 目标与原则

- **目标**：在单标的分析页提供一个**常驻可见**的悬浮「AI 深度分析」入口；点击后**复用最近一次分析
  已取得的数据**，组装单标的 payload → 实时调 AI → 渲染研判结论（可信性 / 风险点 / 操作建议 / 需人工复核项）。
- **原则**：
  1. **零重复取数**：直接读 `st.session_state` 中最近一次分析产出的 `result`/`summary`，不再调用 `fetch_data`/`analyze`。
  2. **引导优先**：FAB 始终渲染且可点；未分析时点击提示「请先开始分析」，AI 关闭时提示配置方法——用引导代替隐藏，保证功能可被发现。
  3. **上下文跟随最近一次分析**：用户改动参数但未重新分析时，FAB 仍可用旧数据研判，**结果区明确标注标的与区间**，避免误判。
  4. **实时调用、不做缓存**：每次点击都实时请求 AI（单标的请求体小，成本可控；结果缓存/当日去重列入第二轮，见 §6）。
  5. **降级优先**：AI 调用失败仅提示，原缠论图/蜡烛图/监控完全不受影响。
  6. **改动收敛、复用底座**：仅在「单标的分析」路径追加出口；客户端、解析、配置、安全约束全部复用
     《收盘分型 AI 研判方案》§6/§8，与 `run_monitor`、批量推送解耦。

---

## 2. 现状（代码探查结论）

| 关注点 | 真实代码 | 本方案利用方式 |
|---|---|---|
| 单标的分析入口 | `web/app.py` 的 `🚀 开始分析` 按钮 → `cached_analysis(...)` | 复用其产出，不重写 |
| 分析产出 | `cached_analysis` 返回 `(result, summary, source_meta)`（`app.py:83-107`） | `result`/`summary` 即 AI 输入源 |
| `result` 结构 | `analyze()` 返回的 DataFrame：含 `datetime/open/high/low/close/volume/amount` 原始列 + `fractal_type`/`is_fractal`/`segment_*` 标记列（`runner.py:107-127`、`chanlun_processor.py:400-403`） | 取尾 `AI_KLINE_WINDOW` 行作 `kline_window` |
| `summary` 结构 | `dict` 含 `fractals`(list[{index,type,high,low,datetime}])、`segments`(list[{start_idx,end_idx,start_type,end_type,direction,start_price,end_price}])、`fractal_count`、`segment_count`（`runner.py:125-126,163-180`） | 直接切片组装 `signals` |
| 名称 | `get_stock_name(stock_code)`（`app.py:416`） | 作为 `signals[].name` |
| 周期参数 | 侧栏 `data_type`（daily/minute）与 `frequency`（`app.py:266-279`） | 写入 `meta`，供 AI 区分日线/分钟线语境 |
| AI 接口参考 | `tests/test_ai_api.py`（OpenAI 兼容连通测试） | 提供调用形态参考：`OpenAI(api_key, base_url, timeout)` + `client.chat.completions.create(..., response_format={"type":"json_object"})` + `models.list()` 验证可用性 |
| AI 模块 | `src/ai/` **尚未实现** | 依赖《收盘分型 AI 研判方案》§6.1（`call_ai`/`parse_review`） |
| AI 配置 | `settings` 暂无 `AI_*`；`base_url`/`token`/`model` 须从 `.env` 读取 | 依赖既有方案 §7 Step 1 先落地配置，且 §6.3 三项凭据均为环境变量 |
| 样式注入 | `web/styles.py::inject_styles()` 通过 `st.markdown(unsafe_allow_html=True)` 注入 CSS | 在此追加 FAB 样式 |

**结论**：单标的的「数据获取」已由现有流程完成，缺的只是「把这份数据交给 AI」的出口与悬浮入口。

---

## 3. 数据准备：单标的 payload 组装

### 3.1 切片口径（不指定锚点，传分型序列）

沿用《收盘分型 AI 研判方案》§4.1 的单条 `signals` 骨架（`meta` + `context` + `signals[1]`），
但**不传 `new_fractal`/`prev_fractal` 单独锚点字段**——单标的是按需分析，最新分型不一定是「今天」的，
故把最近分型序列整体传入，由模型自行判断当前最关键的分型并说明理由：

| 字段 | 来源（单标的） | 说明 |
|---|---|---|
| `code` / `name` | `stock_code` / `get_stock_name(stock_code)` | 定位 / 展示 |
| `recent_fractals` | `summary.fractals` **最后 2 个**（`fractals[-2:]`；连续同型时可能两个都是顶或都是底） | **研判核心**：只送最近两个分型，每个含 `datetime` 生成时间，AI 据此判断当前最值得关注分型 |
| `recent_segments` | `summary.segments` **最后 5 笔** | 上升/下降笔、笔破坏 |
| `kline_window` | `result` 以**最新分型为起点**的后续窗口（`AI_KLINE_WINDOW`，默认 30，硬上限 60） | 量价、趋势（含分型确认后的演化） |
| `last_close` | `result[-1].close` | 最新收盘，作为「当前时点」参照 |
| `meta.data_type` / `meta.frequency` | 侧栏参数 | `daily` 或 `minute_<freq>`，AI 语境必需（分钟线 K 线语义与日线不同） |
| `flow`（资金流，内嵌于 `kline_window` 每条记录） | stockdb 资金流表 `rd.get('资金流', code, date)`，**仅查「最新分型当日及其之后」的交易日** | 主力/超大/大/中/小单净流入(main_net/jumbo_net/big_net/mid_net/small_net)及主力/散户买卖额(main_in/main_out/retail_in/retail_out)，单位元；正=流入、负=流出，辅助判断分型量价配合；无数据日 `flow=null` |

> 价格直接采用 `segment.start_price`/`end_price`（已由 `runner.py:175-176` 注入），不重复反查。
> `kline_window` 字段映射：`{date, open, high, low, close, volume, amount}`，
> `date` 由 `result["datetime"]` 归一（日线 `2026-07-13` → `20260713`；分钟线含时分 `20260713140000`）。
> `flow` 资金流**无开关、默认必须发送**：按每条 K 线的交易日(YYYYMMDD)逐日查询，
> 但只保留 `date >= 最新分型 datetime` 的交易日（即分型当日及其之后），写入该 K 线的 `flow`；
> stockdb 不可用 / 取数失败 / 该日无数据 则 `flow=null` 或不带该字段，**均不阻断 AI 研判**。
> 每个分型的 `datetime` 字段即其**生成时间**，原样透传（如 `20240105`），无需新增字段。
>
> **提示词适配**：既有方案 §4.2 的提示词是「新分型」场景写的，单标的场景须在 user prompt 追加一句：
> 「signals 中未指定单一锚点分型，请基于 recent_fractals 序列自行判断当前最值得关注的分型，并先给出该判断及理由，再展开研判」。

**边界情况**：
- `summary.fractals` 为空（区间内无分型）→ `build_single_payload` 返回 `{}`，调用方跳过 AI（不耗 token）；
- 仅 1 个分型 → 照常传（序列长度 1），由 AI 综合判断；
- 分型 datetime 格式为纯数字字符串（`runner.py:157` 已归一），直接透传。

### 3.2 新增函数 `build_single_payload`

在 `src/ai/review.py` 中新增（切片工具函数与既有 `build_ai_payload` 共用，避免逻辑分叉）：

```python
def build_single_payload(kline_tail, summary, stock_code, stock_name,
                         data_type="daily", frequency=None) -> dict:
    """由单标的分析结果组装 AI 研判 payload。

    - kline_tail: result 尾窗切片（调用方按 AI_KLINE_WINDOW 截取的 DataFrame）
    - summary:    analyze() 返回的汇总 dict（含 fractals / segments）
    - data_type / frequency: 写入 meta，供 AI 区分日线/分钟线语境
    返回结构与《收盘分型 AI 研判方案》§4.1 一致（meta + context + signals[1]）。
    summary 无分型时返回空 dict（调用方据此跳过 AI，省 token）。

    - **不传基本面**：本项目不做基本面研判，settings 中无相关开关。
    - 资金流无开关、默认必须附带；仅查「最新分型当日及之后」的交易日，异常不阻断主流程。
    """
```

- 入参即最近一次分析的产出（经 `st.session_state.ai_ctx` 中转），**不触发任何取数**。
- `signals` 恒为 1 条；`meta.truncated` 对单标的恒为 `false`；`meta` 额外带 `data_type`/`frequency`。

### 3.3 资金流数据来源（stockdb）

资金流来自本地 stockdb 的**资金流表**，经 `src/data/stockdb_fetcher.StockDBFetcher.fetch_money_flow` 封装：

- 取数接口：`rd.get('资金流', code, date)`（`code` 为纯数字、`date` 为 `YYYYMMDD` **字符串**，
  传 int 会返回空记录），逐交易日查询、自动按窗口去重；**实测本机可用**，返回
  `main_net/jumbo_net/big_net/mid_net/small_net` 及 `main_in/main_out/retail_in/retail_out`（单位：元）。
- **查询范围**：只查「最新分型当日及其之后」的交易日（`date >= fractals[-1].datetime`），
  分型之前的日期不查询；分型当日也查（可看出分型形成时资金是否配合）。
- ⚠️ **日期口径必须归一**：`result["datetime"]` 实际是**带横杠字符串**（如 `2026-09-03`），
  而 `fractals[].datetime` 是**纯数字**（如 `20260903`）。统一用 `_yyyymmdd()`
  （只留数字、取前 8 位）归一后再比较与回写；否则 `"2026-09-"[:8]` 会小于 `"20260903"`，
  导致所有日期被过滤、资金流静默取不到（`include_money_flow` 恒为 false）。
- **无开关**：资金流默认必须发送，不提供 `AI_*` 开关（原 `AI_INCLUDE_MONEY_FLOW` 已移除）。
- 注：`ApiDoc.md` §10.2 记录的高层 `get_money_flow(security_list, start_date, end_date)` 在本机
  当前 SDK 版本返回空列表，故实现走底层 `rd.get('资金流', ...)`；后续若该高层接口可用可平滑切换。
- **健壮性（失败不影响主流程）**：`fetch_money_flow` 内单日查询失败仅记 `WARN` 并跳过该日；
  `build_single_payload` 对整个资金流环节（`_fetch_money_flow_map` + 合并）再包一层 `try/except`，
  任何异常都只记 `WARN`、`has_money_flow=False`、`meta.include_money_flow=false`，
  **payload 照常组装、AI 照常研判**（资金流为增强维度，缺失不影响分型/笔逻辑与主流程）。

### 3.4 发送给 AI 的完整内容（不只是 JSON）

一次请求由**三件套**构成（`src/ai/review.py::call_ai`），payload JSON 只是其中之一：

| 组成 | 内容 | 说明 |
|---|---|---|
| `messages[0].role=system` | `_SYSTEM_PROMPT` | 角色定位 + 数据说明 + **防幻觉约束** + 输出 JSON schema |
| `messages[1].role=user` | 自然语言引导句 + payload JSON | **不能只丢 JSON**：弱模型需要明确指令才知道要做什么 |
| 请求参数 | `model` / `response_format=json_object` / `temperature=0.2` / `max_tokens` / `timeout` | 见下 |

**请求参数**
- `response_format={"type": "json_object"}`：强制 JSON 输出（提示词中含 "JSON" 字样以满足该模式要求）。
- `temperature=0.2`：**代码内固定**，不开放为环境变量——技术分析要稳定、可复现，避免同一次分析每次结论不同。
- `max_tokens=AI_MAX_TOKENS`、`timeout=AI_TIMEOUT`：来自 settings。

**系统提示词（`_SYSTEM_PROMPT`）包含**
1. 角色：严谨的缠论（Chan Lun）技术分析助手；
2. 数据说明：`recent_fractals` / `recent_segments` / `kline_window`（以最新分型为起点）/ `last_close` / `meta.data_type`；
3. 资金流 `flow` 各子字段含义与「正=流入、负=流出」判读口径；
4. `context.field_glossary` 为准的字段解读要求；
5. **防幻觉三条铁律**：仅基于所给数据、不得编造（宏观/基本面/新闻/财报等未提供信息）；
   数据不足须如实说明并列入 `need_human_review`；每条结论须可追溯到所给数据；
6. 未指定锚点分型 → 由模型自行锁定最关键分型并填入 `focus_fractal`；
7. 输出 schema（只输出 JSON，无额外文字、无 markdown 围栏）。

**`context` 新增两个辅助字段**（供模型准确解读，避免猜测语义）
- `market_note`：如「A股日线，前复权；分型与笔基于缠论标准定义；本数据仅供辅助研判，不构成投资建议」。
- `field_glossary`：字段词典，明确
  `top=顶分型/bottom=底分型`、`up=上升笔/down=下降笔`、
  `volume` 单位=股、`amount` 单位=元、`flow.*` 各资金流子字段含义、
  `fractal.datetime`=分型生成时间（日线 `YYYYMMDD`、分钟线 `YYYYMMDDHHMMSS`）。

**输出 schema 新增 `focus_fractal`**
```json
"focus_fractal": {"datetime": "所关注分型的生成时间", "type": "top/bottom", "reason": "为什么选它"}
```
用于承接「模型先说明它锁定了哪个分型及理由」——此前该指令没有对应字段，
模型只能塞进 `credibility_reason` 或自造字段（会被 `parse_review` 丢弃）。
`parse_review` 已同步读取并在弹窗「🎯 模型关注的分型」卡片展示。

---

## 4. 悬浮按钮（FAB）实现

### 4.1 渲染时机与引导逻辑（rerun 安全）

**关键约束（Streamlit 生命周期）**：点击 FAB 会触发脚本重跑，重跑时 `if analyze_button` 分支不执行。
因此 FAB 的渲染与点击处理必须放在 `main()` **主流程**（分析分支之外），任何 rerun 都会执行；
分析分支只负责**无条件写入**上下文。`ai_ctx` 的赋值不得依赖任何条件判断（首次分析时它尚不存在）。

分析成功分支末尾（`app.py:502` 之后）——**无条件写入**：

```python
# ── 记录最近一次分析上下文（供 FAB 使用；覆盖式更新）──
st.session_state.ai_ctx = {
    "summary": summary,                                    # 全量（fractals/segments）
    "kline_tail": result.tail(settings.AI_KLINE_WINDOW),   # 尾窗切片，省内存
    "stock_code": stock_code, "stock_name": stock_name,
    "data_type": data_type, "frequency": frequency,
    "start_date": start_date.strftime("%Y-%m-%d"),
    "end_date": end_date.strftime("%Y-%m-%d"),
}
```

主流程（分析分支之外，每次 rerun 执行）：

```python
def _render_ai_fab():
    """渲染悬浮按钮与结果容器（rerun 安全：不放在 if analyze_button 分支内）。"""
    clicked = st.button("🤖 AI 深度分析", key="ai_deep_analysis")
    inject_ai_fab_js()   # ★ 每次 rerun 都要重新注入：Streamlit 重跑会重建 DOM

    if clicked:
        ctx = st.session_state.get("ai_ctx")
        if not settings.AI_ENABLED:
            st.warning("⚠️ AI 未开启：请在 .env 配置 AI_ENABLED=true 与 AI_BASE_URL/AI_MODEL/AI_API_KEY 后重启服务")
        elif ctx is None:
            st.info("👋 请先在左侧点击「🚀 开始分析」，取得分析结果后再深度分析")
        else:
            with st.spinner("🤖 AI 深度分析中…"):
                try:
                    payload = build_single_payload(
                        ctx["kline_tail"], ctx["summary"],
                        ctx["stock_code"], ctx["stock_name"],
                        data_type=ctx["data_type"], frequency=ctx["frequency"],
                        )
                    if not payload:
                        st.warning("该区间未识别出分型，无需 AI 研判")
                    else:
                        resp = call_ai(payload)                 # 每次点击实时调用
                        st.session_state.ai_result = parse_review(resp)
                except Exception as e:
                    logger.error("AI 深度分析失败: %s", e)
                    st.warning("⚠️ AI 研判暂不可用，已保留原分析")

    _render_ai_result()
```

- **AI 关闭**：按钮可点，点击给出配置指引（§1 原则 2）。
- **尚未分析**：按钮可点，点击提示先分析。
- **改参数未重析**：`ai_ctx` 仍是上次分析的数据，FAB 照常可用；结果区标注对应标的与区间（§4.3），不做拦截。
- **失败/降级**：仅 `st.warning`，原图表、蜡烛图、监控按钮全部不受影响。

### 4.2 浮动样式（`web/styles.py`）

在 `inject_styles()` 的 `<style>` 中追加 `.ai-fab` 类；`inject_ai_fab_js()` 通过
`st.components.v1.html(JS, height=0, width=0)` 注入一段 JS，按按钮**唯一 label** 找到该
`stButton` 容器并加浮动类（Streamlit 原生 `st.button` 无法指定 class，故用 JS 定位；
若 JS 不可用则按钮回退为普通按钮出现在结果区，**功能不丢失**）：

```css
.ai-fab > button {
    position: fixed !important;
    right: 28px; bottom: 64px; z-index: 999;
    width: auto !important; min-width: 132px;
    padding: 0.6rem 1.1rem;
    border-radius: 999px;
    background: linear-gradient(135deg, #2563eb, #1e40af);
    color: #fff; font-weight: 600;
    box-shadow: 0 8px 24px rgba(30,64,175,.35);
}
.ai-fab > button:hover { filter: brightness(1.08); }
```

```javascript
// 注入方式：st.components.v1.html(JS, height=0, width=0)
// ★ 必须在每次 rerun 后重新注入（Streamlit 重跑会重建 DOM），由 _render_ai_fab() 调用
const label = "AI 深度分析";
window.parent.document.querySelectorAll("button").forEach(b => {
    if (b.innerText && b.innerText.includes(label)) {
        b.parentElement.classList.add("ai-fab");
    }
});
```

> **避让说明**：Streamlit 自带右下角状态控件（Running/Stop 指示），FAB `bottom` 抬高至 `64px` 错开，
> `z-index: 999` 保证浮于内容之上。
>
> **调用策略**：每次点击**实时调用** AI，不做结果缓存（§1 原则 4）。同一次分析内连点多次会发起
> 多次请求——成本由单标的请求体小（1–2k input tokens）兜底；如需省钱，第二轮可加
> 「FAB 旁强制刷新开关 + 当日去重」（复用《收盘分型 AI 研判方案》§6.6 思路）。

### 4.3 结果展示

```python
def _render_ai_result():
    with st.expander("🤖 AI 深度研判", expanded=bool(st.session_state.get("ai_result"))):
        r = st.session_state.get("ai_result")
        if r is None:
            st.info("点击右下角「🤖 AI 深度分析」获取 AI 研判")
            return
        # ★ 明确标注研判对象，防止「改了参数还没重析」时的误判
        ctx = st.session_state.get("ai_ctx") or {}
        _period = "日线" if ctx.get("data_type") == "daily" else f"{ctx.get('frequency')}分钟线"
        st.caption(
            f"研判对象：{ctx.get('stock_name')}（{ctx.get('stock_code')}）· "
            f"区间 {ctx.get('start_date')} ~ {ctx.get('end_date')} · {_period}"
        )
        st.markdown(f"**可信性**：{r['credibility']} —— {r['credibility_reason']}")
        st.markdown("**风险点**：" + "；".join(r.get("risk_points", [])))
        st.markdown(f"**建议**：{r['suggestion']}（仅供参考，非买卖依据）")
        if r.get("need_human_review"):
            st.warning("需人工复核：" + "；".join(r["need_human_review"]))
```

`ai_result` 每次实时调用后**覆盖式更新**；expander 展开状态跟随是否已有结果。

---

## 5. 集成点清单（文件级）

| # | 文件 | 改动 | 验证 |
|---|------|------|------|
| **1** | `src/ai/review.py` | 新增 `build_single_payload(kline_tail, summary, stock_code, stock_name, data_type, frequency)`；与 `build_ai_payload` 共用切片工具；`meta` 带 `data_type`/`frequency`；空 `fractals` 返回 `{}` | `src/ai/tests/test_payload.py` 加单标的用例：fractals≤8 / segments≤5 / kline≤30 / 空 fractals 返回 `{}` / 仅 1 个分型 / `meta.data_type` 正确 |
| **2** | `web/styles.py` | `inject_styles()` 追加 `.ai-fab` CSS；新增 `inject_ai_fab_js()`（JS 按 label 定位浮动，回退普通按钮；**每次 rerun 需重新调用**） | 页面右下出现圆角悬浮按钮，与状态控件不重叠 |
| **3** | `web/app.py` | 分析成功分支**无条件**写 `st.session_state.ai_ctx`；`main()` 主流程渲染 `_render_ai_fab()`（rerun 安全）+ 引导分支（AI 关/未分析）+ 实时调用；`_render_ai_result()` 展示并标注标的/区间/周期 | 见 §7 |
| **4**（前置/并行） | `src/config/settings.py` + `requirements.txt` | `AI_*` 配置与 `openai` 依赖（**依赖《收盘分型 AI 研判方案》§7 Step 1/3/8 已落地**）；本方案不新增环境变量 | `settings.AI_ENABLED` 可读 |
| **5** | `README.md` | 新增「单标的 AI 深度分析」小节：入口、引导逻辑、研判对象标注、降级说明 | 文档审阅通过 |

**不改动**：`runner.analyze` / `_extract_segments`、`cached_analysis` 取数逻辑、`monitor_job`、绘图
（`plotly_viz`）、收盘监控批量推送。本方案是既有分析流程的**纯增量出口**。

---

## 6. 配置 / 安全 / 成本（复用既有约束）

- **配置（凭据全部来自 `.env`）**：复用《收盘分型 AI 研判方案》§6.3 的 `AI_*`
  （`AI_ENABLED`/`AI_BASE_URL`/`AI_MODEL`/`AI_API_KEY`/`AI_TIMEOUT`/`AI_MAX_TOKENS`/
  `AI_MAX_RETRY`/`AI_KLINE_WINDOW`）。
  **`base_url`、`token`(API Key)、`model` 三项均从 `.env` 读取，绝不硬编码**（见下例）。
  悬浮按钮不新增环境变量；**资金流无开关，默认必须发送**（见 §3.3）；
  **不做基本面研判，已移除 `AI_INCLUDE_FUNDAMENTALS`**；
  `temperature` 在代码中固定为 `0.2`（技术分析需稳定可复现），不开放为环境变量。

  `.env` 示例：
  ```dotenv
  AI_ENABLED=true
  AI_BASE_URL=https://<你的OpenAI兼容端点>/v1      # 本地 Ollama 填 http://host.docker.internal:11434/v1
  AI_MODEL=auto                                  # 模型名由服务端决定
  AI_API_KEY=<从服务商获取，绝不入库/不打印>
  AI_TIMEOUT=60
  AI_MAX_TOKENS=4000
  AI_MAX_RETRY=1
  AI_KLINE_WINDOW=30
  # （不做基本面研判；个股日资金流默认必须发送，均无环境变量开关）
  ```

  `call_ai` 参考 `tests/test_ai_api.py` 的调用形态（OpenAI 兼容 SDK）：
  `OpenAI(api_key=os.environ["AI_API_KEY"], base_url=os.environ["AI_BASE_URL"], timeout=AI_TIMEOUT)`，
  调用 `client.chat.completions.create(model=AI_MODEL, messages=[...], response_format={"type":"json_object"}, max_tokens=AI_MAX_TOKENS)`；
  联通自检可用 `models.list()` 验证认证与可用性。
  **注意**：该参考文件目前仍硬编码了 key 与端点（即审核报告 P0-1 所指），落地时应改为从 `.env` 读取、
  `AI_API_KEY` 缺失则 `unittest.skip`（你已轮换 key，此处仅提醒文件级清理）。
- **安全**：`AI_API_KEY` 仅环境变量读取（§8）；`parse_review` 校验 `code` ∈ 请求集合（防幻觉）；
  超时/重试沿用 `AI_TIMEOUT`/`AI_MAX_RETRY`。
- **成本**：每次点击**实时调用**（评审决策：取最简实现），单标的请求 ≈ 1–2k input / 500–800 output tokens，
  远低于批量监控，输出截断风险可忽略；连点多次的成本由请求体小兜底。
  **结果缓存 / 当日去重（含强制刷新开关）列入第二轮**，复用《收盘分型 AI 研判方案》§6.6 思路。
- **降级**：AI 关闭 → 点击给配置指引；调用异常 → 仅 warning，原分析图与监控照常。

---

## 7. 验证计划

1. **AI 关闭态**：`AI_ENABLED=False` → FAB 仍显示且可点，点击提示配置方法；「开始分析」一切照旧。
2. **未分析态**：新开会话直接点 FAB → 提示「请先开始分析」。
3. **正常态**：分析一只股（如 `600588.SH`）→ 点 FAB → `expander` 展开研判，顶部 caption 标注
   标的/区间/周期；每次点击均发起 1 次实时 AI 请求。
4. **旧上下文态**：分析 A 后修改代码/日期但不重析 → 点 FAB 仍基于 A 研判，结果区标注为 A（无拦截）。
5. **边界**：选无分型的极短区间 → 提示「未识别出分型，无需研判」，不调 AI；仅 1 个分型 → 正常研判。
6. **降级态**：`AI_BASE_URL` 填错 / 断网 → 点击后 `st.warning`，缠论图与蜡烛图仍在。
7. **单测**：`pytest src/ai/tests/test_payload.py` —— 单标的切片口径、`meta` 周期字段、空 `summary` 与单分型分支。

---

## 8. 与《收盘分型 AI 研判方案》的边界

| 维度 | 既有方案（批量收盘监控） | 本方案（单标的悬浮） |
|---|---|---|
| 触发场景 | 「🚀 立即执行收盘监控」扫描全市场新分型 | 「🚀 开始分析」后按需点悬浮按钮 |
| 数据来源 | `monitor_job` 的 `items` | 同一页面最近一次 `cached_analysis` 的 `result`/`summary` |
| payload 组装 | `build_ai_payload(items)`，含 `new_fractal`/`prev_fractal` 锚点 | `build_single_payload(...)`，**不指定锚点**，传分型序列 + `data_type`/`frequency` |
| 提示词 | 「新分型」场景（既有 §4.2） | 追加「由 AI 自行判断当前最关键分型」一句 |
| 调用策略 | 每周期聚合 1 次请求 | 每次点击实时调用 |
| 结果缓存 | §6.6 当日去重 | 第二轮再加（本方案无缓存） |
| AI 客户端/解析 | `call_ai` / `parse_review` | **同一套** |
| 配置/安全 | `AI_*` / §8 | **同一套，无新增** |

两者共用 `src/ai` 与 `AI_*`，**互不冲突**；本方案只给单标的分析加一个独立出口。
