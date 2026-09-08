"""src/ai/review.py - AI 研判客户端与 payload 组装（OpenAI 兼容）。

核心函数：
  - call_ai(payload) -> str        ：构造请求、调用大模型、返回 JSON 文本
  - parse_review(text) -> dict    ：解析返回文本为标准化研判 dict
  - build_single_payload(...)      ：组装单标的深度分析 payload（悬浮按钮用）

安全约束（与《收盘分型 AI 研判方案》§6/§8 一致）：
  - API Key / Base URL / Model 全部来自 src.config.settings（仅环境变量读取，绝不硬编码）；
  - parse_review 对返回做字段归一与兜底，缺字段给默认值，避免前端因 KeyError 崩溃。
"""
from __future__ import annotations

import json
import logging
import time

from src.config import settings
from src.utils.logger import get_logger

# 必须用项目的 get_logger（而非原生 logging.getLogger）：原生方式没有 handler，
# 只有 WARNING+ 会经 lastResort 输出，导致「开始请求 AI」等 INFO 日志在 cmd 里看不到。
# LoggerAdapter 给每条日志统一补 component=AI 标签（控制台/文件/前端环形缓冲三处一致）。
logger = logging.LoggerAdapter(get_logger(__name__), {"component": "AI"})

# ---------------------------------------------------------------------------
# 系统提示词（单标的场景）
# 说明：signals 中未指定单一锚点分型，让模型基于 recent_fractals 自行判断最关键分型。
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "你是一名严谨的缠论（Chan Lun）技术分析助手。用户会提供一只标的的最近分型序列"
    "（recent_fractals）、最近笔段（recent_segments）、量价 K 线窗口（kline_window）"
    "与最新收盘（last_close），以及周期（meta.data_type: daily/minute）。\n"
    "其中 kline_window 是以「最新分型」为起点的后续 K 线窗口，包含该分型本身及之后"
    "每一根的 open/high/low/close/volume/amount（即分型确认后的量价演化），"
    "请重点结合这部分量价关系研判分型的有效性与后续走势。\n"
    "kline_window 中每根 K 线可能附带 flow 字段（个股日资金流，单位元；为 null 表示该日无数据）："
    "含主力净流入 main_net、超大/大/中/小单净流入(jumbo_net/big_net/mid_net/small_net)"
    "及主力/散户买卖额(main_in/main_out/retail_in/retail_out)。请结合主力净流入方向"
    "（正=资金流入、负=资金流出）与量价关系，判断分型确认时资金是否配合，"
    "以提升分型可信性判断的准确度。\n"
    "context.field_glossary 给出了各字段的准确含义（含 top/bottom、up/down、"
    "volume/amount 单位、flow 各子字段等），解读数据时一律以它为准。\n"
    "严格约束（防幻觉，必须遵守）：\n"
    "1) 仅基于所给数据研判，不得编造或臆测未提供的信息（如宏观、基本面、新闻、财报等）；\n"
    "2) 数据缺失或不足以支撑结论时，如实说明「数据不足」，并把该项列入 need_human_review；\n"
    "3) 每条结论都要能追溯到所给数据中的具体依据。\n"
    "注意：signals 中未指定单一锚点分型，请基于 recent_fractals 序列自行判断当前"
    "最值得关注的分型，并把该判断填入 focus_fractal 字段（含其 datetime、type 与选择理由）。\n"
    "必须只输出一个 JSON 对象，不要任何额外文字、不要 markdown 代码围栏，字段如下：\n"
    "{\n"
    '  "code": "标的代码(与输入一致)",\n'
    '  "focus_fractal": {"datetime": "所关注分型的生成时间", "type": "top/bottom",'
    ' "reason": "为什么选它"},\n'
    '  "credibility": "高/中/低",\n'
    '  "credibility_reason": "可信性判断理由",\n'
    '  "risk_points": ["风险点1", "风险点2"],\n'
    '  "suggestion": "操作建议(仅供参考，非买卖依据)",\n'
    '  "need_human_review": ["需人工复核的项"]\n'
    "}"
)


def _to_jsonable(v):
    """把 numpy 类型等转为原生 Python 类型，便于 JSON 序列化。"""
    try:
        import numpy as np

        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass
    return v


def _kline_to_records(df):
    """把 K 线 DataFrame 尾窗转为记录列表，日期归一为整数串。"""
    if df is None:
        return []
    recs = []
    for _, row in df.iterrows():
        dt = row.get("datetime")
        if hasattr(dt, "strftime"):
            # 日线（无时分）→ 20260713；分钟线（含时分）→ 20260713140000
            date_str = (
                dt.strftime("%Y%m%d")
                if (dt.hour == 0 and dt.minute == 0)
                else dt.strftime("%Y%m%d%H%M%S")
            )
        else:
            date_str = str(dt)
        recs.append(
            {
                "date": date_str,
                "open": _to_jsonable(row.get("open")),
                "high": _to_jsonable(row.get("high")),
                "low": _to_jsonable(row.get("low")),
                "close": _to_jsonable(row.get("close")),
                "volume": _to_jsonable(row.get("volume")),
                "amount": _to_jsonable(row.get("amount")),
            }
        )
    return recs


def _yyyymmdd(v) -> str:
    """把日期表示归一为 8 位 YYYYMMDD（剔除分隔符、只留数字、取前 8 位）。

    ⚠️ 必须归一：`result["datetime"]` 实际是带横杠的字符串（如 "2026-09-03"），
    而 `fractals[].datetime` 是纯数字（如 "20260903"）。若直接比较，
    "2026-09-"[:8] 会小于 "20260903"，导致所有日期被过滤、资金流永远取不到。
    """
    return "".join(ch for ch in str(v) if ch.isdigit())[:8]


def _fetch_money_flow_map(kline_records, stock_code, fractal_day=None):
    """按 K 线窗口交易日取资金流，返回 ({date8: flow_dict}, available_bool)。

    交易日从每条记录的 date 字段前 8 位(YYYYMMDD)提取并去重，避免逐根重复查询；
    给了 fractal_day 时只保留 d >= fractal_day 的交易日，即「最新分型当日及其之后」，
    不查询分型之前的日期。stockdb 不可用时捕获异常返回 ({}, False)，
    上层据此跳过、不阻断 AI 研判。
    """
    try:
        from src.data.stockdb_fetcher import StockDBFetcher
    except Exception:
        return {}, False
    day_floor = _yyyymmdd(fractal_day) if fractal_day else None
    dates = []
    for r in kline_records:
        d = _yyyymmdd(r.get("date", ""))
        if len(d) != 8 or d in dates:
            continue
        if day_floor and d < day_floor:   # 只查分型当日及之后
            continue
        dates.append(d)
    if not dates:
        return {}, False
    try:
        mf_map = StockDBFetcher().fetch_money_flow(stock_code, dates)
    except Exception as e:
        logger.warning("资金流获取失败，跳过: %s", e)
        return {}, False
    return (mf_map, bool(mf_map))


def call_ai(payload: dict) -> str:
    """调用 OpenAI 兼容大模型，返回 JSON 文本。

    凭据与模型全部来自 settings（环境变量）。失败时抛出异常，由上层降级为 warning。
    """
    if not settings.AI_ENABLED:
        raise RuntimeError("AI 未开启（AI_ENABLED != true）")
    if not settings.AI_API_KEY or not settings.AI_BASE_URL or not settings.AI_MODEL:
        raise RuntimeError("AI 配置不全：请在 .env 配置 AI_BASE_URL/AI_MODEL/AI_API_KEY")

    try:
        from openai import OpenAI
    except ImportError as e:  # openai 未安装时给出明确错误
        raise RuntimeError("openai 未安装：请 pip install openai 后重试") from e

    payload_str = json.dumps(payload, ensure_ascii=False)
    # user 消息 = 自然语言任务引导 + JSON 数据。
    # 不能只丢一个 JSON：弱模型（含本地小模型）需要一句明确的指令才知道要做什么。
    user_msg = (
        "请依据系统提示词的要求，研判下面这只标的的缠论分型数据，"
        "并严格按约定的 JSON 字段输出结果（只输出 JSON，不要其他文字）：\n"
        + payload_str
    )
    max_retry = max(1, settings.AI_MAX_RETRY)
    logger.info(
        "开始请求 AI | model=%s base_url=%s timeout=%ss max_retry=%d payload_chars=%d",
        settings.AI_MODEL,
        settings.AI_BASE_URL or "(none)",
        settings.AI_TIMEOUT,
        max_retry,
        len(payload_str),
    )

    client = OpenAI(
        api_key=settings.AI_API_KEY,
        base_url=settings.AI_BASE_URL or None,
        timeout=settings.AI_TIMEOUT,
    )

    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            logger.info("AI 调用尝试 %d/%d ...", attempt, max_retry)
            t0 = time.perf_counter()
            resp = client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                # 固定低温度：技术分析要稳定可复现，按约定不开放为配置项
                temperature=0.2,
                max_tokens=settings.AI_MAX_TOKENS,
                timeout=settings.AI_TIMEOUT,
            )
            text = resp.choices[0].message.content
            cost = time.perf_counter() - t0
            logger.info(
                "AI 调用成功 | attempt=%d 耗时=%.2fs 返回字符数=%d",
                attempt,
                cost,
                len(text or ""),
            )
            return text
        except Exception as e:  # 重试后由上层处理
            last_err = e
            logger.warning("AI 调用失败（将重试 %d/%d）: %s", attempt, max_retry, e)
    logger.error("AI 调用最终失败（已重试 %d 次）: %s", max_retry, last_err)
    raise last_err or RuntimeError("AI 调用失败")


def parse_review(text: str) -> dict:
    """解析大模型返回的 JSON 文本为标准化研判 dict。

    返回字段：code / focus_fractal / credibility / credibility_reason /
    risk_points / suggestion / need_human_review。缺字段给默认值，避免前端 KeyError。
    """
    data = {}
    if text:
        try:
            data = json.loads(text)
        except Exception as e:
            logger.error("AI 返回解析失败: %s", e)
            data = {}
    if not isinstance(data, dict):
        data = {}

    logger.info(
        "AI 研判解析完成 | code=%s credibility=%s risk_points=%d need_review=%d",
        data.get("code", ""),
        data.get("credibility", "未知"),
        len(data.get("risk_points") or []),
        len(data.get("need_human_review") or []),
    )
    _focus = data.get("focus_fractal")
    if not isinstance(_focus, dict):
        _focus = {}
    return {
        "code": data.get("code", ""),
        "focus_fractal": _focus,
        "credibility": data.get("credibility", "未知"),
        "credibility_reason": data.get("credibility_reason", ""),
        "risk_points": data.get("risk_points") or [],
        "suggestion": data.get("suggestion", ""),
        "need_human_review": data.get("need_human_review") or [],
    }


def build_single_payload(
    kline_tail,
    summary,
    stock_code,
    stock_name,
    data_type="daily",
    frequency=None,
) -> dict:
    """由单标的分析结果组装 AI 研判 payload（悬浮按钮用）。

    - kline_tail: result 尾窗切片（调用方按 AI_KLINE_WINDOW 截取的 DataFrame）
    - summary:    analyze() 返回的汇总 dict（含 fractals / segments）
    - data_type / frequency: 写入 meta，供 AI 区分日线/分钟线语境
    返回结构与《收盘分型 AI 研判方案》§4.1 一致（meta + context + signals[1]）。
    summary 无分型时返回空 dict（调用方据此跳过 AI，省 token）。

    - **不传基本面**：本项目不做基本面研判，config 中亦无相关开关。
    - 资金流：**无开关，默认必须附带**。仅查询「最新分型当日及其之后」的交易日资金流；
      取数任一环节异常都被捕获并记录，绝不阻断 payload 组装（失败则记录但不带 flow）。
    """
    summary = summary or {}
    fractals = summary.get("fractals") or []
    if not fractals:
        logger.info("AI payload 跳过：未识别到分型，无需研判")
        return {}

    segments = summary.get("segments") or []
    logger.info(
        "开始组装 AI payload | code=%s name=%s 分型总数=%d",
        stock_code, stock_name, len(fractals),
    )
    kline_window = _kline_to_records(kline_tail)[: settings.AI_KLINE_WINDOW]
    last_close = kline_window[-1]["close"] if kline_window else None

    # 资金流：仅查「最新分型当日及之后」的交易日；任一异常都不影响主流程
    has_money_flow = False
    if kline_window:
        try:
            fractal_day = _yyyymmdd(fractals[-1].get("datetime", ""))
            logger.info(
                "资金流开始获取 | code=%s 分型日期=%s 窗口根数=%d",
                stock_code, fractal_day, len(kline_window),
            )
            mf_map, has_money_flow = _fetch_money_flow_map(
                kline_window, stock_code, fractal_day=fractal_day
            )
            if has_money_flow:
                for rec in kline_window:
                    # 必须与 _fetch_money_flow_map 用同一套归一口径，否则查得到却匹配不上
                    d = _yyyymmdd(rec.get("date", ""))
                    rec["flow"] = mf_map.get(d)   # None 表示该日无资金流数据
                logger.info(
                    "资金流获取成功 | code=%s 交易日数=%d",
                    stock_code, len(mf_map),
                )
            else:
                logger.warning(
                    "资金流获取失败或为空 | code=%s（已跳过，不影响研判）", stock_code
                )
        except Exception as e:   # 资金流为增强维度，失败仅降级，绝不阻断研判
            logger.warning("资金流处理失败，已跳过（不影响研判）: %s", e)
            has_money_flow = False

    logger.info(
        "AI payload 组装完成 | code=%s kline_window=%d recent_fractals=%d "
        "recent_segments=%d money_flow=%s",
        stock_code, len(kline_window), len(fractals[-2:]),
        len(segments[-5:]), has_money_flow,
    )
    _period_label = "日线" if data_type == "daily" else f"{frequency}分钟线"
    return {
        "meta": {
            "data_type": data_type,
            "frequency": frequency,
            "truncated": False,
            "include_money_flow": has_money_flow,
        },
        "context": {
            # 市场语境与字段词典：让模型不必猜测 top/bottom、up/down、单位等语义
            # 注：不写嵌套 f-string（Python <3.12 会报 SyntaxError），先算好周期标签
            "market_note": (
                f"A股{_period_label}，前复权；分型与笔基于缠论标准定义；"
                "本数据仅供辅助研判，不构成投资建议。"
            ),
            "field_glossary": {
                "fractal_type": "top=顶分型(可能回调), bottom=底分型(可能反弹)",
                "fractal_datetime": "该分型的生成时间，日线为 YYYYMMDD，分钟线为 YYYYMMDDHHMMSS",
                "segments.direction": "up=上升笔, down=下降笔",
                "segments.start_price/end_price": "该笔起止分型对应的价格",
                "kline_window": "以「最新分型」为起点的K线窗口（含分型当日及其之后），"
                                "每根含 date/open/high/low/close/volume/amount",
                "kline_window.volume": "成交量，单位：股",
                "kline_window.amount": "成交额，单位：元",
                "kline_window.flow": "个股当日资金流，单位：元；main_net=主力净流入"
                                     "(正=资金流入，负=资金流出)；"
                                     "jumbo_net/big_net/mid_net/small_net=超大/大/中/小单净流入；"
                                     "main_in/main_out=主力买入/卖出额；"
                                     "retail_in/retail_out=散户买入/卖出额；"
                                     "该字段为 null 表示当日无资金流数据",
            },
            "kline_window": kline_window,
            "last_close": last_close,
        },
        "signals": [
            {
                "code": stock_code,
                "name": stock_name,
                "recent_fractals": fractals[-2:],   # 最近 2 个分型
                "recent_segments": segments[-5:],   # 最近 5 笔
            }
        ],
    }
