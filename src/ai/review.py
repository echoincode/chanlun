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
import os
import time
from datetime import datetime

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
    "与最新收盘（last_close），以及周期（meta.data_type: daily/minute）。"
    "kline_window 是以「最新分型」为起点的后续 K 线（含分型当日及其后），"
    "即分型确认后的量价演化。\n"
    "- recent_fractals[] 字段：datetime(YYYYMMDD)/type(top|bottom)/high/low/strength；"
    "strength=分型强弱(strong|weak)：strong=第1根K即创新高(顶)/新低(底)、反转果断、可作有效反转信号；"
    "weak=第3根K仍创新高(顶)/新低(底)、属中继型、不构成有效反转。\n"
    "【数据字典】所有字段含义与单位以此为准，无需再做任何换算：\n"
    "- kline_window 基础字段：date(日线YYYYMMDD/分钟YYYYMMDDHHMMSS)、"
    "open/high/low/close(元)、vol_wan(成交量,万股)、amount_wan(成交额,万元)。\n"
    "- kline_window.turnover：换手率%（仅日线；null=该日无数据）。\n"
    "- kline_window 指标字段：vol_ratio(量比,>1放量/<1缩量)、"
    "macd_hist(MACD柱,>0多头/由正转负≈死叉)、rsi(14周期,>70超买/<30超卖)、"
    "above_ma20(收盘是否在20日均线上方,布尔)、ma_trend(均线排列:多头排列/空头排列/纠缠)。\n"
    "- kline_window.flow（日资金流，单位万元；null=该日无数据）：main_net_wan=主力净流入"
    "(正=流入/负=流出)、jumbo_net_wan=超大单净额、big_net_wan=大单净额、"
    "mid_net_wan=中单净额、small_net_wan=小单净额。\n"
    "- kline_window.margin（融资融券，单位万元，仅日线）：fin_value_wan=融资余额、"
    "fin_buy_wan=融资买入额、fin_net_buy_wan=融资净买入(买入-偿还)。"
    "融资余额上升/净买入放大=杠杆资金看多，反之撤退。\n"
    "- context.indicators：最新分型当日指标快照（macd_dif/macd_dea/macd_hist、rsi、"
    "boll_upper/boll_mid/boll_lower、vol_ratio、turnover、above_ma20、ma_trend）。\n"
    "- context.upcoming_unlocks：未来N交易日限售解禁列表{day,num,rate1,rate2}；"
    "rate1/rate2 为 0~1 小数(0.7077=70.77%)，rate2>0.05 即明显抛压。\n"
    "- context.computed_stats：代码预先精确计算的聚合数字。"
    "change_since_fractal_pct=分型首根收盘→最新收盘涨跌幅%；window_high/window_low="
    "窗口最高/最低价；main_net_sum_wan=窗口内主力净流入合计(万元,负=净流出)；"
    "main_net_out_days/main_net_in_days=净流出/净流入天数；main_net_last_wan=末日净流入；"
    "fin_value_first/last/change_wan=融资余额首末值及变化(万元)；"
    "max_unlock_rate2_next30d=未来30日最大解禁占流通股本比例。\n"
    "- context.fact_card：代码按确定性规则预计算的派生事实。"
    "consecutive_down_days=窗口内连续收跌天数；broke_fractal_low=是否已跌破分型日最低价；"
    "vol_trend=量能趋势(放量/缩量/平稳,后5日均量vs前5日均量)；macd_hist_signs="
    "逐日MACD柱符号串(如\"+++---\")；macd_cross=金叉/死叉发生日(无则null)；"
    "macd_divergence=顶/底背离检测结果(type/evidence,未检出为null)；"
    "flow_last_positive_date=主力资金末次净流入为正的日期；margin_up_days=融资余额连升天数；"
    "structure=当前笔结构位置(隐含新笔方向/距分型根数/近5笔平均长度/运行进度%)；"
    "prev_same_type_fractal=前一同类型分型区间(重要支撑/阻力参考)。\n"
    "- context.data_coverage：各维度数据在窗口内的实际覆盖天数(kline_rows=总根数)。\n"
    "【数据可用性（重要，接口偶发取不到数据）】某维度覆盖为 0 =「本次缺失」："
    "对应 confirmations 维度必须填 unknown，不得作为命中项或反向证据，"
    "并在 need_human_review 注明「XX数据缺失」；部分覆盖时只使用有数据的天，"
    "不得假设缺失日无异动。严禁编造缺失维度的任何数值或形态"
    "（曾出现无数据却称「MACD顶背离」的幻觉）。\n"
    "【引用纪律（模型算术曾多次出错）】所有跨日聚合数字（累计资金流、区间涨跌幅、"
    "融资余额变化、连涨连跌天数、背离判定等）一律直接引用 computed_stats / fact_card "
    "的现成值，严禁自行加总、换算或数天数；两处均未提供的数字一律用定性描述"
    "（如「大幅流出」「温和放量」），不要给出自行计算的精确值。\n"
    "credibility（可信性）评级标准——务必据此给出明确的 高/中/低，不得一律给「中」：\n"
    "  - 高：分型形态标准成立，且量价按分型方向兑现（顶分型：破位下行/连续收跌=兑现；"
    "底分型：守住低点或放量反弹），"
    "且 MACD 同向（底分型 MACD 金叉或底背离、顶分型 死叉或顶背离），"
    "且资金流同向（底分型主力净流入 / 顶分型主力净流出），"
    "且融资余额趋势同向（底分型融资余额升/融资买入放大、顶分型融资余额降），"
    "且与当前笔或更大级别结构同向，且近期无大额限售解禁；\n"
    "  - 中：分型形态成立，但缺一项确认——量能未明显放大（vol_ratio≈1、换手率平淡）/ "
    "MACD 未明显金叉或背离 / 资金流方向不明或与分型反向力度弱 / 融资余额走平无倾向 / "
    "笔结构既未被破坏也未强化 / 无更大级别印证；\n"
    "  - weak 分型（strength=weak，第3根K仍创新高/低的中继型）：默认不构成有效反转，"
    "credibility 不得评「高」；仅当价格已明确突破该分型极值且量价/资金/MACD 多维度强确认时，"
    "最多评「中」。\n"
    "  - 低：分型孤立、处于笔中段、量价反向（顶分型后却创新高、底分型后却破位）、"
    "资金流明显反向、MACD 明显反向（顶分型却金叉）/ "
    "或处于重要阻力/支撑位却未能确认突破，或未来 N 日有 rate2>0.05 的限售解禁形成供给抛压。\n"
    "  - 约束：若 upcoming_unlocks 存在 rate2>0.05（占流通股本 5% 以上）的解禁，必须将其列入 risk_points，"
    "并据此下调底分型可信度（至少降一档）。\n"
    "  - 语义说明（重要）：credibility 评级对象是「信号发出时点的质量」，"
    "即该分型在产生时有多少确认项支持它，由打分卡推演得出；"
    "信号发出后的兑现情况由 signal_status（待确认/已兑现/已失效）单独表达，"
    "兑现后的前瞻应对写在 suggestion。因此：分型后走势大幅兑现（如顶分型后已跌超 10%）"
    "恰恰说明信号质量高，不得因「已兑现、后续参考价值下降」而压低 credibility；"
    "也不得出现「分型已大跌 20% 却称其低可信」的自相矛盾表述。\n"
    "严格约束（防幻觉，必须遵守）：\n"
    "1) 仅基于所给数据研判，不得编造或臆测未提供的信息（如宏观、基本面、新闻、财报等）；\n"
    "2) confirmations 打分卡必须 7 个维度逐项给出（先填卡、后下结论），"
    "status 只能取 hit/miss/unknown；各维度 hit 的含义=「该确认项成立、支持分型信号」：\n"
    "   form=分型形态标准成立；price_volume=量价按分型方向兑现"
    "（极性按分型类型判定，严禁套错方向：顶分型=分型后破位下行/连续收跌记 hit、"
    "企稳反弹收复分型高点才记 miss；底分型=守住分型低点或放量反弹记 hit、"
    "跌破分型低点记 miss——跌破分型低点对顶分型是兑现、对底分型才是失效）；"
    "macd=MACD 同向（金叉死叉/背离方向与分型匹配）；money_flow=主力资金方向与分型同向；"
    "margin=融资余额趋势与分型同向；structure=与当前笔或更大级别结构同向；"
    "unlock=无大额解禁抛压（注意：unlock 的 hit=无解禁=通过，miss=有大额解禁=风险，"
    "与其他维度相反）；\n"
    "3) 每条结论都要能追溯到所给数据中的具体依据，credibility 必须与打分卡一致；\n"
    "4) 若已有量价与资金流足以支撑判断，必须给出明确的 高/中/低，不得回避到「中」；\n"
    "5) 中文表达（重要，界面直接展示给用户）：evidence、credibility_reason、risk_points、"
    "suggestion 必须是通顺的中文，严禁出现内部字段名与代码式赋值"
    "（如 computed_stats.main_net_sum_wan=-40202.5、fact_card.broke_fractal_low=true、"
    "macd_cross=20260901）；应转述为自然语言并换算为亿/万（如「主力资金累计净流出约4.02亿元」"
    "「已跌破分型日最低价」「9月1日出现MACD死叉」）；credibility_reason 中提及维度一律用"
    "中文名（分型形态/量价/MACD/主力资金/融资/笔结构/解禁），不得罗列英文键名。\n"
    "注意：signals 中未指定单一锚点分型，请基于 recent_fractals 序列自行判断当前"
    "最值得关注的分型，并把该判断填入 focus_fractal 字段（含其 datetime、type 与选择理由）。\n"
    "必须只输出一个 JSON 对象，不要任何额外文字、不要 markdown 代码围栏，字段如下：\n"
    "{\n"
    '  "code": "标的代码(与输入一致)",\n'
    '  "focus_fractal": {"datetime": "所关注分型的生成时间", "type": "top/bottom",'
    ' "reason": "为什么选它"},\n'
    '  "confirmations": {\n'
    '    "form":         {"status": "hit/miss/unknown", "evidence": "一句话依据"},\n'
    '    "price_volume": {"status": "hit/miss/unknown", "evidence": "一句话依据"},\n'
    '    "macd":         {"status": "hit/miss/unknown", "evidence": "一句话依据"},\n'
    '    "money_flow":   {"status": "hit/miss/unknown", "evidence": "一句话依据"},\n'
    '    "margin":       {"status": "hit/miss/unknown", "evidence": "一句话依据"},\n'
    '    "structure":    {"status": "hit/miss/unknown", "evidence": "一句话依据"},\n'
    '    "unlock":       {"status": "hit/miss/unknown", "evidence": "一句话依据"}\n'
    "  },\n"
    '  "credibility": "高/中/低（与打分卡一致，评级对象是信号发出时点的质量）",\n'
    '  "signal_status": "分型信号状态：待确认/已兑现/已失效'
    '（结合 computed_stats.change_since_fractal_pct 判断）",\n'
    '  "credibility_reason": "简短中文总结：命中/缺失了哪些确认项（用中文名），'
    '对应标准哪一级；严禁出现字段名",\n'
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
            # datetime 列可能是带横杠的字符串（如 "2026-08-24"，本次 000973 案例即如此）。
            # 必须归一为纯数字：_compute_indicators 的 ind_map 键是 8/14 位数字，
            # 若 rec["date"] 带横杠，ind_map.get(rec["date"]) 永远取不到，
            # 导致 MACD 等指标「算出来了却挂不上」（meta 谎报 include_indicators=True）。
            date_str = "".join(ch for ch in str(dt).strip() if ch.isdigit())[:14]
        if not date_str:   # 极端兜底：全非数字时保留原串，不让记录丢日期
            date_str = str(dt)
        # A 层简化：量/额在源头换算成万单位，模型侧不再需要任何 ÷1e4/÷1e8 换算
        # （多位数裸数字是历次算术错误的直接土壤，见 _compute_stats 注释）
        _vol = _to_jsonable(row.get("volume"))
        _amt = _to_jsonable(row.get("amount"))
        recs.append(
            {
                "date": date_str,
                "open": _to_jsonable(row.get("open")),
                "high": _to_jsonable(row.get("high")),
                "low": _to_jsonable(row.get("low")),
                "close": _to_jsonable(row.get("close")),
                "vol_wan": (
                    _round(_vol / 1e4, 1)
                    if isinstance(_vol, (int, float)) else None),
                "amount_wan": (
                    _round(_amt / 1e4, 1)
                    if isinstance(_amt, (int, float)) else None),
            }
        )
    return recs


def _normalize_dt_key(dt) -> str:
    """把 datetime 归一为与 _kline_to_records 产出的 record['date'] 完全一致：
    日线 -> 'YYYYMMDD'（8 位无分隔符），分钟线 -> 'YYYYMMDDHHMMSS'（14 位）。

    修复：ind_map 的键必须与 kline_window 的 date 同口径，否则挂载时取不到值，
    导致 MACD 等指标算出来了却没挂上去（meta 标 include_indicators=True 但数据缺失）。
    """
    if dt is None:
        return ""
    if hasattr(dt, "strftime"):
        return (
            dt.strftime("%Y%m%d")
            if (dt.hour == 0 and dt.minute == 0)
            else dt.strftime("%Y%m%d%H%M%S")
        )
    # 已是字符串（如 "2026-09-03" / "2026-09-03 14:00:00"）：剔除分隔符只留数字
    digits = "".join(ch for ch in str(dt).strip() if ch.isdigit())
    return digits[:14]


def _yyyymmdd(v) -> str:
    """把日期表示归一为 8 位 YYYYMMDD（剔除分隔符、只留数字、取前 8 位）。

    ⚠️ 必须归一：`result["datetime"]` 实际是带横杠的字符串（如 "2026-09-03"），
    而 `fractals[].datetime` 是纯数字（如 "20260903"）。若直接比较，
    "2026-09-"[:8] 会小于 "20260903"，导致所有日期被过滤、资金流永远取不到。
    """
    return "".join(ch for ch in str(v) if ch.isdigit())[:8]


def _round(v, nd=4):
    """把数值安全四舍五入到 nd 位；None / NaN / Inf 返回 None（便于 JSON 序列化）。"""
    try:
        import math
        if v is None:
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, nd)
    except Exception:
        return None


def _compute_indicators(full_df):
    """本地用 pandas 计算 MACD/RSI/BOLL/MA/量比/振幅，返回 {标准化日期: {...}}。

    - 基于完整序列（建议 >=35 根以稳定 MACD），再按日期映射到窗口各根 K 线；
    - 日期键与 _kline_to_records 同口径（日线 8 位、分钟 14 位），便于直接挂载；
    - 任一异常返回 {}，上层据此跳过、绝不阻断 payload 组装。
    """
    try:
        import pandas as pd
        import numpy as np
    except Exception:
        return {}
    if full_df is None or len(full_df) < 2:
        return {}
    try:
        df = full_df.copy()
        df["_dt"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["_dt"]).sort_values("_dt").reset_index(drop=True)
        if df.empty:
            return {}
        close = pd.to_numeric(df["close"], errors="coerce")
        # volume/high/low 缺失时降级为全 NaN，保证 MACD/RSI/BOLL/MA 等收盘衍生指标仍可算
        _nan = pd.Series(np.nan, index=df.index)
        vol = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else _nan
        high = pd.to_numeric(df["high"], errors="coerce") if "high" in df.columns else _nan
        low = pd.to_numeric(df["low"], errors="coerce") if "low" in df.columns else _nan
        if close.isna().all():
            return {}
    except Exception:
        return {}

    n = len(df)
    vol_ma5 = vol.rolling(5, min_periods=1).mean()
    vol_ratio = vol / vol_ma5.replace(0, np.nan)
    pre_close = close.shift(1)
    amplitude = (high - low) / pre_close.replace(0, np.nan) * 100

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = (dif - dea) * 2

    # RSI 用 Wilder 平滑（alpha=1/period），比简单滚动均值更贴近通用口径
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)

    boll_mid = close.rolling(20, min_periods=1).mean()
    boll_std = close.rolling(20, min_periods=1).std(ddof=0)
    boll_upper = boll_mid + 2 * boll_std
    boll_lower = boll_mid - 2 * boll_std

    ma5 = close.rolling(5, min_periods=1).mean()
    ma10 = close.rolling(10, min_periods=1).mean()
    ma20 = close.rolling(20, min_periods=1).mean()

    out = {}
    for i in range(n):
        # 关键：键必须和 _kline_to_records 产出的 record["date"] 同口径（归一化、无横杠），
        # 否则下方挂载循环 ind_map.get(rec["date"]) 取不到值，MACD 等指标算出来却挂不上去。
        key = _normalize_dt_key(df.iloc[i]["datetime"])
        out[key] = {
            "vol_ratio": _round(vol_ratio.iloc[i]),
            "amplitude": _round(amplitude.iloc[i]),
            "macd_dif": _round(dif.iloc[i]),
            "macd_dea": _round(dea.iloc[i]),
            "macd_hist": _round(macd_hist.iloc[i]),
            "rsi": _round(rsi.iloc[i]),
            "boll_upper": _round(boll_upper.iloc[i]),
            "boll_mid": _round(boll_mid.iloc[i]),
            "boll_lower": _round(boll_lower.iloc[i]),
            "ma5": _round(ma5.iloc[i]),
            "ma10": _round(ma10.iloc[i]),
            "ma20": _round(ma20.iloc[i]),
        }
    return out


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


# A 层简化：flow 只保留 5 个净额字段（买卖额可由净额推导，删除冗余防干扰）
_FLOW_KEYS = ("main_net", "jumbo_net", "big_net", "mid_net", "small_net")


def _flow_to_wan(flow):
    """资金流 元→万元（round2），只保留 5 个净额字段。"""
    if not isinstance(flow, dict):
        return None
    out = {}
    for k in _FLOW_KEYS:
        v = flow.get(k)
        out[f"{k}_wan"] = (
            _round(v / 1e4, 2) if isinstance(v, (int, float)) else None)
    return out


def _margin_to_wan(margin):
    """两融 元→万元（round2），只留 融资余额/融资买入/融资净买入 三个核心字段
    （两融余额=融资+融券市值、融券各字段量级极小且实测从未被引用，删冗余）。"""
    if not isinstance(margin, dict):
        return None

    def _w(key):
        v = margin.get(key)
        return _round(v / 1e4, 2) if isinstance(v, (int, float)) else None

    buy = margin.get("fin_buy_value")
    refund = margin.get("fin_refund_value")
    net = (buy - refund) if (
        isinstance(buy, (int, float)) and isinstance(refund, (int, float))
    ) else None
    return {
        "fin_value_wan": _w("fin_value"),
        "fin_buy_wan": _w("fin_buy_value"),
        "fin_net_buy_wan": _round(net / 1e4, 2) if net is not None else None,
    }


def _detect_divergence(full_series):
    """B 层：在完整序列尾部检测 MACD 顶/底背离（确定性代码计算，替代模型目测）。

    简化口径：取最近 120 根内相邻的两个摆动高点（±3 根窗口内的局部最大收盘），
    价创新高而 DIF 回落 → 顶背离；摆动低点价创新低而 DIF 回升 → 底背离。
    检不出返回 None。任何异常返回 None，绝不阻断 payload 组装。
    """
    try:
        import pandas as pd
        df = full_series.copy()
        df["_dt"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["_dt"]).sort_values("_dt").reset_index(drop=True)
        close = pd.to_numeric(df["close"], errors="coerce")
        if len(close) < 40:
            return None
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        n = len(df)
        lo = max(0, n - 120)

        def _swings(is_high):
            pts = []
            for i in range(max(3, lo), min(n - 3, n)):
                seg = close.iloc[i - 3: i + 4]
                if is_high and close.iloc[i] == seg.max():
                    if not pts or close.iloc[i] != close.iloc[pts[-1]]:
                        pts.append(i)
                elif (not is_high) and close.iloc[i] == seg.min():
                    if not pts or close.iloc[i] != close.iloc[pts[-1]]:
                        pts.append(i)
            # 合并相邻同向摆动（保留极值更极端的那个）
            merged = []
            for i in pts:
                if merged and ((close.iloc[i] - close.iloc[merged[-1]]) >= 0) == is_high:
                    if (close.iloc[i] > close.iloc[merged[-1]]) == is_high:
                        merged[-1] = i
                else:
                    merged.append(i)
            return merged

        for is_high in (True, False):
            sw = _swings(is_high)
            if len(sw) < 2:
                continue
            a, b = sw[-2], sw[-1]
            if is_high and close.iloc[b] > close.iloc[a] and dif.iloc[b] < dif.iloc[a]:
                return {
                    "type": "顶背离",
                    "evidence": (
                        f"价 {close.iloc[b]:.2f}>{close.iloc[a]:.2f} 创新高，"
                        f"DIF {dif.iloc[b]:.3f}<{dif.iloc[a]:.3f} 回落"),
                }
            if (not is_high) and close.iloc[b] < close.iloc[a] and dif.iloc[b] > dif.iloc[a]:
                return {
                    "type": "底背离",
                    "evidence": (
                        f"价 {close.iloc[b]:.2f}<{close.iloc[a]:.2f} 创新低，"
                        f"DIF {dif.iloc[b]:.3f}>{dif.iloc[a]:.3f} 回升"),
                }
        return None
    except Exception as e:
        logger.warning("MACD 背离检测失败（不影响研判）: %s", e)
        return None


def _build_fact_card(kline_window, fractals, segments, unlock_list, divergence):
    """B 层：中性事实卡——代码可确定性算出的派生事实，模型只解读不计算。

    注意保持「中性」：只陈述计数/符号/日期，不写「看空/利好」等结论性措辞，
    避免预设结论污染模型判断。
    """
    fc = {}
    if not kline_window:
        return fc

    closes = [r.get("close") for r in kline_window
              if isinstance(r.get("close"), (int, float))]
    # 连续收跌/收明天数（自窗口第 2 根起）
    if len(closes) >= 2:
        down = 0
        for a, b in zip(closes, closes[1:]):
            if b < a:
                down += 1
            else:
                break
        fc["consecutive_down_days"] = down
    # 是否跌破分型日最低价（分型低点 = 窗口首根 low）
    fractal_low = kline_window[0].get("low")
    if isinstance(fractal_low, (int, float)) and len(closes) >= 2:
        fc["broke_fractal_low"] = bool(min(closes[1:]) < fractal_low)
    # 量能趋势：后 5 日均量 vs 前 5 日均量
    vols = [r.get("vol_wan") for r in kline_window
            if isinstance(r.get("vol_wan"), (int, float))]
    if len(vols) >= 4:
        mid = len(vols) // 2
        prev_avg = sum(vols[:mid]) / max(1, mid)
        last_avg = sum(vols[mid:]) / max(1, len(vols) - mid)
        if prev_avg:
            ratio = last_avg / prev_avg
            fc["vol_trend"] = (
                "放量" if ratio >= 1.2 else "缩量" if ratio <= 0.8 else "平稳")
            fc["vol_trend_ratio"] = _round(ratio, 2)
    # MACD 柱符号串与金叉/死叉日
    signs = []
    cross_day = None
    prev_sign = None
    for r in kline_window:
        h = r.get("macd_hist")
        s = "?" if h is None else ("+" if h > 0 else "-" if h < 0 else "0")
        if (prev_sign in ("+", "-") and s in ("+", "-") and s != prev_sign
                and cross_day is None):
            cross_day = r.get("date")
        signs.append(s)
        prev_sign = s
    fc["macd_hist_signs"] = "".join(signs)
    if cross_day:
        fc["macd_cross"] = cross_day
    if divergence:
        fc["macd_divergence"] = divergence
    # 主力资金末次净流入为正的日期
    for r in reversed(kline_window):
        f = r.get("flow")
        if isinstance(f, dict) and isinstance(f.get("main_net_wan"), (int, float)):
            if f["main_net_wan"] > 0:
                fc["flow_last_positive_date"] = r.get("date")
            break
    # 融资余额连升天数
    fins = [r["margin"]["fin_value_wan"] for r in kline_window
            if isinstance(r.get("margin"), dict)
            and isinstance(r["margin"].get("fin_value_wan"), (int, float))]
    if len(fins) >= 2:
        up = 0
        for a, b in zip(fins, fins[1:]):
            if b > a:
                up += 1
            else:
                break
        fc["margin_up_days"] = up
    # 笔结构位置：隐含新笔方向 + 运行进度（相对近 5 笔平均长度）
    if segments and fractals:
        lens = [s.get("end_idx", 0) - s.get("start_idx", 0)
                for s in segments[-5:]]
        lens = [x for x in lens if x > 0]
        avg_len = _round(sum(lens) / len(lens), 1) if lens else None
        last_seg = segments[-1]
        offset = len(kline_window) - 1
        fc["structure"] = {
            "prev_stroke_direction": last_seg.get("direction"),
            "implicit_new_stroke_direction": (
                "down" if last_seg.get("direction") == "up" else "up"),
            "bars_since_fractal": offset,
            "avg_stroke_len_5": avg_len,
            "progress_vs_avg_pct": (
                _round(offset / avg_len * 100, 1) if avg_len else None),
        }
    # 前一同类型分型区间（重要支撑/阻力）
    focus_type = fractals[-1].get("type") if fractals else None
    # focus 分型强弱（strong/weak）：中继型 weak 不构成有效反转，供模型评级参考
    focus_strength = fractals[-1].get("strength") if fractals else None
    if focus_strength:
        fc["focus_fractal_strength"] = focus_strength
    if focus_type:
        for f in reversed(fractals[:-1]):
            if f.get("type") == focus_type:
                fc["prev_same_type_fractal"] = {
                    # 与 payload 其他日期同口径（8 位纯数字），datetime 可能是 Timestamp
                    "datetime": _yyyymmdd(f.get("datetime", "")),
                    "high": f.get("high"),
                    "low": f.get("low"),
                }
                break
    return fc


def _compute_stats(kline_window, unlock_list):
    """代码侧预先精确计算聚合数字，供模型直接引用（禁止模型自行加总/换算）。

    背景：LLM 对多位数加总不可靠，实测两次出现累计净流出算错
    （写 1.73 亿实为 2.53 亿、写 3.51 亿实为 4.51 亿）。
    因此所有跨日聚合（累计净流入、区间涨跌幅、融资余额变化等）一律在此算好，
    payload 的 context.computed_stats 原样带给模型，提示词强制其直接引用。
    """
    s = {}
    if not kline_window:
        return s
    closes = [r.get("close") for r in kline_window
              if isinstance(r.get("close"), (int, float))]
    if closes:
        s["change_since_fractal_pct"] = (
            round((closes[-1] - closes[0]) / closes[0] * 100, 2)
            if closes[0] else None)
    highs = [r.get("high") for r in kline_window
             if isinstance(r.get("high"), (int, float))]
    lows = [r.get("low") for r in kline_window
            if isinstance(r.get("low"), (int, float))]
    if highs:
        s["window_high"] = max(highs)
    if lows:
        s["window_low"] = min(lows)

    # 资金流聚合（万元）：只统计有数据的天，缺失天不参与。
    # flow 已在挂载时转为 *_wan（见 _flow_to_wan），此处直接求和，无任何换算。
    nets = [r["flow"].get("main_net_wan") for r in kline_window
            if isinstance(r.get("flow"), dict)
            and isinstance(r["flow"].get("main_net_wan"), (int, float))]
    s["flow_days_with_data"] = len(nets)
    s["flow_days_total"] = len(kline_window)
    if nets:
        s["main_net_sum_wan"] = _round(sum(nets), 1)
        s["main_net_out_days"] = sum(1 for n in nets if n < 0)
        s["main_net_in_days"] = sum(1 for n in nets if n > 0)
        s["main_net_last_wan"] = _round(nets[-1], 1)

    # 融资余额首末变化（万元）：margin 已转为 *_wan（见 _margin_to_wan）
    fins = [r["margin"]["fin_value_wan"] for r in kline_window
            if isinstance(r.get("margin"), dict)
            and isinstance(r["margin"].get("fin_value_wan"), (int, float))]
    if len(fins) >= 2:
        s["fin_value_first_wan"] = _round(fins[0], 1)
        s["fin_value_last_wan"] = _round(fins[-1], 1)
        s["fin_value_change_wan"] = _round(fins[-1] - fins[0], 1)

    # 未来 30 日最大解禁占流通股本比例（0~1 小数，无解禁则不给）
    if unlock_list:
        rates = [u.get("rate2") for u in unlock_list
                 if isinstance(u, dict) and isinstance(u.get("rate2"), (int, float))]
        if rates:
            s["max_unlock_rate2_next30d"] = max(rates)
    return s


def _data_coverage(kline_window):
    """统计各增强维度在窗口内的实际覆盖天数，让模型不必猜「有没有这条数据」。

    背景：meta.include_* 只说明「组装时是否启用」，部分天缺失（接口偶发取不到）
    时模型无从得知。覆盖为 0 = 该维度本次完全缺失；部分覆盖 = 只有列出的天有数据。
    """
    def _hit(key):
        return sum(1 for r in kline_window if r.get(key) is not None)
    return {
        "kline_rows": len(kline_window),
        "money_flow_days": _hit("flow"),
        "margin_days": _hit("margin"),
        "indicator_days": sum(1 for r in kline_window
                              if r.get("macd_hist") is not None),
        "turnover_days": _hit("turnover"),
    }


def call_ai(payload: dict, extra_user_note: str = None) -> str:
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
    if extra_user_note:
        user_msg = extra_user_note + "\n\n" + user_msg
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


def validate_review(payload: dict, review: dict) -> list:
    """对 AI 返回做规则校验（C 层守门），返回问题列表（空列表 = 通过）。

    校验分层：
      1. 结构合法性：credibility 枚举、confirmations 打分卡 7 维度齐全、status 枚举；
      2. 数据可用性一致性：coverage=0 的维度 status 必须为 unknown（防幻觉）；
      3. 打分卡-评级一致性：代码按打分卡推演评级，与模型自评矛盾则打回；
      4. 数字一致性：reason 中「累计N亿」与 computed_stats 比对（±15% 容差）。
    """
    problems = []
    if review.get("credibility") not in ("高", "中", "低"):
        problems.append(
            f"credibility 非法: {review.get('credibility')!r}，必须是 高/中/低")

    meta = (payload or {}).get("meta") or {}
    ctx = (payload or {}).get("context") or {}
    coverage = ctx.get("data_coverage") or {}
    reason = str(review.get("credibility_reason") or "")

    # --- 2. 打分卡结构 + 数据可用性一致性 ---
    conf = review.get("confirmations")
    if not isinstance(conf, dict) or not conf:
        problems.append(
            "缺少 confirmations 打分卡或其为空；必须对 form/price_volume/macd/"
            "money_flow/margin/structure/unlock 7 个维度逐项给出 "
            "{status: hit/miss/unknown, evidence}")
    else:
        _REQUIRED_STATUS = ("hit", "miss", "unknown")
        # 维度 → 覆盖度键；unlock 特殊：用 meta.include_unlock（None=查询失败）
        _DIM_COVER = {
            "form": coverage.get("kline_rows"),
            "price_volume": coverage.get("kline_rows"),
            "macd": coverage.get("indicator_days"),
            "money_flow": coverage.get("money_flow_days"),
            "margin": coverage.get("margin_days"),
            "structure": coverage.get("kline_rows"),
            "unlock": None,   # 单独处理
        }
        for dim in ("form", "price_volume", "macd", "money_flow",
                    "margin", "structure", "unlock"):
            d = conf.get(dim)
            if not isinstance(d, dict) or d.get("status") not in _REQUIRED_STATUS:
                problems.append(
                    f"confirmations.{dim} 缺失或 status 非法"
                    f"（必须是 hit/miss/unknown）")
                continue
            status = d["status"]
            if dim == "unlock":
                data_ok = bool(meta.get("include_unlock"))
            else:
                cov = _DIM_COVER[dim]
                data_ok = isinstance(cov, (int, float)) and cov > 0
            if not data_ok and status != "unknown":
                problems.append(
                    f"confirmations.{dim} 的数据本次缺失，status 必须为 unknown，"
                    f"不得给出 hit/miss 判断")
        # 数据在而标 unknown：允许（模型可判断该维度与本次分型无关），不报问题

        # --- 2.5 打分卡极性检查（量价维度按分型方向判定，曾出现顶分型兑现却记 miss）---
        pv = conf.get("price_volume")
        ftype = ((review.get("focus_fractal") or {}).get("type") or "")
        broke = (ctx.get("fact_card") or {}).get("broke_fractal_low")
        if (isinstance(pv, dict) and broke is True
                and ftype == "top" and pv.get("status") == "miss"):
            problems.append(
                "极性错误：顶分型后已跌破分型日最低价（破位下行），这是下跌兑现、"
                "量价确认成立，price_volume 应记 hit 而非 miss"
                "（跌破分型低点只对底分型才是失效）")
        if (isinstance(pv, dict) and broke is True
                and ftype == "bottom" and pv.get("status") == "hit"):
            problems.append(
                "极性错误：底分型后已跌破分型日最低点，信号已失效，"
                "price_volume 应记 miss 而非 hit")

        # --- 3. 打分卡-评级一致性推演 ---
        if all(isinstance(conf.get(d), dict)
               and conf[d].get("status") in _REQUIRED_STATUS
               for d in ("form", "price_volume", "macd", "money_flow",
                         "margin", "structure", "unlock")):
            misses = [d for d in ("form", "price_volume", "macd", "money_flow",
                                  "margin", "structure", "unlock")
                      if conf[d]["status"] == "miss"]
            core_miss = [d for d in ("form", "macd", "money_flow")
                         if conf[d]["status"] == "miss"]
            hits = [d for d, v in conf.items() if v.get("status") == "hit"]
            if review.get("credibility") == "高" and (core_miss or len(misses) >= 2):
                problems.append(
                    f"credibility=高 但打分卡存在 miss 项（{misses}），相互矛盾；"
                    f"存在核心维度 miss 或 ≥2 个 miss 时不得评高")
            if review.get("credibility") == "低" and not misses:
                problems.append(
                    "credibility=低 但打分卡无任何 miss 项；低评级必须对应至少一个"
                    "未确认/反向维度（或凭 signal_status=已兑现说明评的是后续参考价值）")

    # --- 4. 数字一致性（保留旧检查作为兜底） ---
    _missing_kw = ("缺失", "null", "无数据", "未提供", "未返回", "N/A", "无该数据")
    _has_missing_note = any(k in reason for k in _missing_kw)
    if not meta.get("include_indicators", False):
        _low = reason.lower()
        if ("macd" in _low or "rsi" in _low) and not _has_missing_note:
            problems.append(
                "indicators 数据缺失，credibility_reason 却引用 MACD/RSI 且未注明缺失")
    if not meta.get("include_money_flow", False):
        if "主力" in reason and not _has_missing_note:
            problems.append("资金流数据缺失，credibility_reason 却引用主力资金且未注明缺失")
    import re
    stats = ctx.get("computed_stats") or {}
    sum_wan = stats.get("main_net_sum_wan")
    if isinstance(sum_wan, (int, float)) and "累计" in reason:
        expect_yi = abs(sum_wan) / 1e4
        cited = [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*亿", reason)]
        if cited and not any(
                abs(n - expect_yi) <= max(0.15 * expect_yi, 0.05) for n in cited):
            problems.append(
                f"累计主力资金数字与 computed_stats 不符：代码计算 {expect_yi:.2f}亿，"
                f"报告引用 {cited}；请直接引用 computed_stats.main_net_sum_wan")

    # --- 5. 中文表达检查（报告直接展示给用户，严禁内部字段名/代码式赋值）---
    _texts = [reason]
    _texts += [str(r) for r in (review.get("risk_points") or [])]
    if isinstance(conf, dict):
        _texts += [str(v.get("evidence", ""))
                   for v in conf.values() if isinstance(v, dict)]
    blob = " ".join(_texts)
    _RAW_TOKENS = ("computed_stats", "fact_card", "data_coverage",
                   "upcoming_unlocks", "broke_fractal_low", "macd_cross",
                   "main_net", "change_since_fractal", "prev_same_type",
                   "flow_last_positive", "margin_up_days", "_wan",
                   "=true", "=false", "vol_ratio=", "include_")
    _found = [t for t in _RAW_TOKENS if t in blob]
    if _found:
        problems.append(
            f"报告中出现内部字段名/代码式表达（{_found}），必须改写为通顺中文："
            "字段值转述为自然语言（如「主力资金累计净流出约4.02亿元」「9月1日MACD死叉」），"
            "维度用中文名，不得罗列英文键名")
    return problems


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
    _conf = data.get("confirmations")
    if not isinstance(_conf, dict):
        _conf = {}
    return {
        "code": data.get("code", ""),
        "focus_fractal": _focus,
        "confirmations": _conf,
        "credibility": data.get("credibility", "未知"),
        "signal_status": data.get("signal_status", ""),
        "credibility_reason": data.get("credibility_reason", ""),
        "risk_points": data.get("risk_points") or [],
        "suggestion": data.get("suggestion", ""),
        "need_human_review": data.get("need_human_review") or [],
    }


# AI 分析结果留存目录：项目根下的 output/ai_analysis/
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "ai_analysis",
)


def save_ai_analysis(stock_code, payload, review, ctx=None):
    """将 AI 深度分析的「发送内容(payload)」与「返回结果(review)」留存到 output/ai_analysis/。

    每次分析生成一个 JSON 文件（命名：{code}_{YYYYMMDD_HHMMSS}.json），文件内同时包含
    sent_payload、review 与 system_prompt，便于事后完整复现与核对
    「用了什么提示词 + 发了什么数据 → 模型回了什么」。

    设计要点：
      - 任一异常都被捕获并记录日志，绝不阻断主流程（分析失败不应因写盘而中断）；
      - 用 os.makedirs(exist_ok=True) 懒创建目录，首次分析即自动建好 output/ai_analysis/。
    """
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{stock_code}_{ts}.json"
        fpath = os.path.join(OUTPUT_DIR, fname)
        ctx = ctx or {}
        record = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "stock_code": stock_code,
            "stock_name": ctx.get("stock_name", ""),
            "data_type": ctx.get("data_type", ""),
            "frequency": ctx.get("frequency", ""),
            # 提示词与模型一并留存，保证事后可复现（system_prompt=_SYSTEM_PROMPT 常量，
            # 与 call_ai 实际发给模型的 system 完全一致）
            "model": getattr(settings, "AI_MODEL", ""),
            "system_prompt": _SYSTEM_PROMPT,
            "sent_payload": payload,
            "review": review,
        }
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        logger.info("AI 分析留存成功 | code=%s file=%s", stock_code, fpath)
        return fpath
    except Exception as e:
        logger.warning("AI 分析留存失败（不影响研判）: %s", e)
        return None


def build_single_payload(
    kline_tail,
    summary,
    stock_code,
    stock_name,
    data_type="daily",
    frequency=None,
    full_series=None,
) -> dict:
    """由单标的分析结果组装 AI 研判 payload（悬浮按钮用）。

    - kline_tail: result 尾窗切片（调用方按 AI_KLINE_WINDOW 截取的 DataFrame）
    - summary:    analyze() 返回的汇总 dict（含 fractals / segments）
    - data_type / frequency: 写入 meta，供 AI 区分日线/分钟线语境
    - full_series: 完整序列（可选）。用于本地计算 MACD/RSI/BOLL/MA/量比/振幅；
      不传则跳过技术指标（窗口通常仅 30 根，不足以稳定 MACD，必须基于完整序列计算）。
    返回结构与《收盘分型 AI 研判方案》§4.1 一致（meta + context + signals[1]）。
    summary 无分型时返回空 dict（调用方据此跳过 AI，省 token）。

    - **不传基本面**：本项目不做基本面研判，config 中亦无相关开关。
    - 资金流：**无开关，默认必须附带**。仅查询「最新分型当日及其之后」的交易日资金流；
      取数任一环节异常都被捕获并记录，绝不阻断 payload 组装（失败则记录但不带 flow）。
    - 技术指标：**无开关，默认附带**（本地 pandas 计算，零外部依赖）。指标挂到窗口每根 K 线，
      并给出「最新分型当日」快照 context.indicators；失败则跳过（meta.include_indicators=False）。
    - 换手率：仅日线附带（经 rd.get_data 拉取），分钟线无该字段故跳过；失败同样降级不阻断。
    - 融资融券：仅日线附带，按窗口交易日区间查询后挂到每根 K 线的 margin 字段；
      非两融标的/无数据时为空（meta.include_margin=False），失败降级不阻断。
    - 限售解禁：仅日线附带，查「最后一根 K 线之后 30 个交易日」的解禁写入 context.upcoming_unlocks；
      用 None 区分「查询失败」与「查询成功但无解禁」(空列表)，meta.include_unlock 表示是否查询成功。
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
                    # A 层简化：挂载时即转万元、删冗余子字段
                    rec["flow"] = _flow_to_wan(mf_map.get(d))   # None 表示该日无资金流数据
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

    # 技术指标（本地 pandas 计算，零外部依赖）：基于完整序列算 MACD/RSI/BOLL/MA/量比/振幅，
    # 再按日期映射到窗口各根 K 线；任一异常都不影响主流程。
    ind_map = {}
    _divergence = None
    if full_series is not None:
        try:
            logger.info("技术指标开始计算 | code=%s 完整序列根数=%d", stock_code, len(full_series))
            ind_map = _compute_indicators(full_series)
        except Exception as e:
            logger.warning("技术指标计算失败，已跳过（不影响研判）: %s", e)
            ind_map = {}
        # B 层：MACD 顶/底背离检测（确定性代码计算，替代模型目测 K 线找背离）
        _divergence = _detect_divergence(full_series)
        if _divergence:
            logger.info("MACD 背离检测 | code=%s 结果=%s", stock_code, _divergence.get("type"))

    # 扩展行情字段：换手率 turnover（仅日线；经 rd.get_data 拉取，纯增强维度）
    turn_map = {}
    if data_type == "daily" and kline_window:
        try:
            from src.data.stockdb_fetcher import StockDBFetcher
            _dates = [r["date"] for r in kline_window]
            turn_map = StockDBFetcher().fetch_quote_extra(stock_code, _dates, fields=("turnover",))
        except Exception as e:
            logger.warning("换手率获取失败，已跳过（不影响研判）: %s", e)
            turn_map = {}

    # 融资融券（杠杆资金多空，仅日线）：按窗口交易日区间查，挂到每根 K 线
    margin_map = {}
    if data_type == "daily" and kline_window:
        try:
            from src.data.stockdb_fetcher import StockDBFetcher
            _m_dates = [r["date"] for r in kline_window]
            logger.info(
                "融资融券开始获取 | code=%s 窗口根数=%d",
                stock_code, len(kline_window),
            )
            margin_map = StockDBFetcher().fetch_margin_trading(stock_code, _m_dates)
            if margin_map:
                logger.info(
                    "融资融券获取成功 | code=%s 交易日数=%d",
                    stock_code, len(margin_map),
                )
            else:
                logger.warning(
                    "融资融券获取失败或为空 | code=%s（已跳过，不影响研判）", stock_code
                )
        except Exception as e:
            logger.warning("融资融券处理失败，已跳过（不影响研判）: %s", e)
            margin_map = {}

    # 限售解禁（供给抛压，仅日线）：取最后一根 K 线之后 forward_count 个交易日
    # None = 未查询/查询失败；[] = 查询成功但近期无解禁。二者语义不同，弹窗据此如实标注。
    unlock_list = None
    if data_type == "daily" and kline_window:
        try:
            from src.data.stockdb_fetcher import StockDBFetcher
            _last_date = kline_window[-1].get("date", "")
            logger.info(
                "限售解禁开始获取 | code=%s 起始日=%s 向前交易日=%d",
                stock_code, _last_date, 30,
            )
            unlock_list = StockDBFetcher().fetch_locked_shares(
                stock_code, start_date=_last_date, forward_count=30)
            if unlock_list:   # [] 表示查询成功但近期无解禁
                logger.info(
                    "限售解禁获取成功 | code=%s 解禁笔数=%d",
                    stock_code, len(unlock_list),
                )
            else:
                logger.warning(
                    "限售解禁获取失败或为空 | code=%s（已跳过，不影响研判）", stock_code
                )
        except Exception as e:
            logger.warning("限售解禁处理失败，已跳过（不影响研判）: %s", e)
            unlock_list = None

    # 把技术指标 / 换手率 / 融资融券 挂到窗口每根 K 线（缺字段则该根为 None，不影响模型读取）
    # A 层简化：均线(am5/10/20)与振幅不再原样附带，替换为派生结论 above_ma20 / ma_trend
    _ind_attached = False
    for rec in kline_window:
        _k = rec.get("date", "")
        # 双键兜底：日期归一后正常应直接命中；万一上游仍传回带横杠的字符串，
        # 再用纯数字键取一次，确保本地算好的指标绝不因键口径而丢失
        _kd = "".join(ch for ch in str(_k) if ch.isdigit())[:14]
        _ind = ind_map.get(_k) or ind_map.get(_kd)
        if _ind:
            rec["vol_ratio"] = _ind.get("vol_ratio")
            rec["macd_hist"] = _ind.get("macd_hist")
            rec["rsi"] = _ind.get("rsi")
            _c, _m5 = rec.get("close"), _ind.get("ma5")
            _m10, _m20 = _ind.get("ma10"), _ind.get("ma20")
            rec["above_ma20"] = (
                _c > _m20 if isinstance(_c, (int, float))
                and isinstance(_m20, (int, float)) else None)
            if all(isinstance(v, (int, float))
                   for v in (_m5, _m10, _m20) if v is not None) and None not in (_m5, _m10, _m20):
                rec["ma_trend"] = (
                    "多头排列" if _m5 > _m10 > _m20
                    else "空头排列" if _m5 < _m10 < _m20 else "纠缠")
            else:
                rec["ma_trend"] = None
            _ind_attached = True
        # 换手率 key 用 8 位纯数字（rd.get_data 返回整数日期），与记录 date 的连字符格式对齐
        _k8 = "".join(ch for ch in str(_k) if ch.isdigit())[:8]
        _t = turn_map.get(_k8)
        if isinstance(_t, dict) and _t.get("turnover") is not None:
            rec["turnover"] = _t["turnover"]
        _m = _margin_to_wan(margin_map.get(_k8))
        if _m:   # 转换成功才挂载，避免出现全 None 的占位 dict 干扰覆盖度统计
            rec["margin"] = _m

    # 焦点快照 = 窗口首根（即最新分型当日）的核心指标 + 换手率 + 均线派生结论。
    # 注意：必须以本地计算的 _fi 非空为前提——只有 turnover（外部接口字段）时
    # 不得声称有 indicators（曾因只带 turnover 导致 meta 谎报 include_indicators=True，
    # 模型误以为有 MACD 可用）。
    focus_ind = None
    if kline_window:
        _fk = kline_window[0].get("date", "")
        _fk8 = "".join(ch for ch in str(_fk) if ch.isdigit())[:14]
        _t0 = turn_map.get(_fk8) or {}
        _fi = dict(ind_map.get(_fk) or ind_map.get(_fk8) or {})
        if _fi:
            focus_ind = {
                "macd_dif": _fi.get("macd_dif"),
                "macd_dea": _fi.get("macd_dea"),
                "macd_hist": _fi.get("macd_hist"),
                "rsi": _fi.get("rsi"),
                "boll_upper": _fi.get("boll_upper"),
                "boll_mid": _fi.get("boll_mid"),
                "boll_lower": _fi.get("boll_lower"),
                "vol_ratio": _fi.get("vol_ratio"),
                "above_ma20": kline_window[0].get("above_ma20"),
                "ma_trend": kline_window[0].get("ma_trend"),
            }
            if _t0.get("turnover") is not None:
                focus_ind["turnover"] = _t0.get("turnover")

    # 如实反映指标是否真的挂到了窗口（而非仅算出来）：键不匹配会导致算出来了却挂不上。
    # 只看 _ind_attached（窗口内真实挂上），focus_ind 为 None（连首根都没有）也如实为 False。
    _has_ind = _ind_attached
    _has_turn = bool(turn_map)
    _has_margin = bool(margin_map)
    _has_unlock = unlock_list is not None
    # 代码侧精确聚合 + 覆盖度统计 + 中性事实卡：根治模型算术错误，并让模型明白数据缺什么
    _coverage = _data_coverage(kline_window)
    _stats = _compute_stats(kline_window, unlock_list)
    _fact_card = _build_fact_card(
        kline_window, fractals, segments, unlock_list, _divergence)
    logger.info(
        "AI payload 组装完成 | code=%s kline_window=%d recent_fractals=%d "
        "recent_segments=%d money_flow=%s indicators=%s turnover=%s margin=%s "
        "unlock=%s divergence=%s",
        stock_code, len(kline_window), len(fractals[-2:]),
        len(segments[-5:]), has_money_flow, _has_ind, _has_turn, _has_margin,
        _has_unlock, (_divergence or {}).get("type", "无"),
    )
    return {
        "meta": {
            "data_type": data_type,
            "frequency": frequency,
            "truncated": False,
            "include_money_flow": has_money_flow,
            "include_indicators": _has_ind,
            "include_turnover": _has_turn,
            "include_margin": _has_margin,
            "include_unlock": _has_unlock,
        },
        "context": {
            # A 层简化：字段词典与市场语境为常量，已上移至系统提示词（利于前缀缓存），
            # payload 只保留纯数据，可读性与 token 效率兼得。
            "indicators": focus_ind,
            "data_coverage": _coverage,
            "computed_stats": _stats,
            "fact_card": _fact_card,
            "upcoming_unlocks": unlock_list or [],
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
