"""每日收盘分型监控任务（由 Web 按钮手动触发，也可命令行执行）。

职责（对齐 docs/daily_fractal_monitor.md）：
  1. 非交易日（周末）直接退出；
  2. 按 settings.MONITOR_CODES 逐个取数（经 StockDBFetcher 拉取，本地缓存优先）；
  3. analyze 计算分型，按回看窗口定位“本次分型”；
  4. 与 state/<code>.json 上次快照对比，去重后只推送“新分型”；
  5. 按模板组装 markdown 卡片（仅列出最近两次分型：类型 + 生成时间，不比较是否新分型）；
  6. 通过 get_notifiers() 按配置推送（配置几个发几个），更新快照；
  7. 暴露 run_monitor() 供 Web 按钮 import 复用，返回结构化结果。

用法：
  - 命令行：  python scripts/monitor_job.py
  - Web 按钮：from scripts.monitor_job import run_monitor; run_monitor()
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

# 允许从任意工作目录直接运行
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.config import settings
from src.data.stockdb_fetcher import StockDBFetcher
from src.data.kline_cache import load_or_fetch
from src.cli.runner import analyze
from src.notify import get_notifiers, Notifier
from src.data.stock_names import get_stock_name
from src.utils.logger import get_logger

logger = get_logger(__name__)

STATE_DIR = os.path.join(_PROJECT_ROOT, "state")


def _safe_print(text: str) -> None:
    """控制台安全打印：Windows gbk 终端无法编码 emoji 等字符时降级替换。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", "replace").decode("gbk", "replace"))


def _state_path(code: str) -> str:
    return os.path.join(STATE_DIR, f"{code.replace('.', '_')}.json")


def _load_state(code: str) -> dict:
    import json

    path = _state_path(code)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(code: str, state: dict) -> None:
    import json

    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_path(code), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _fmt_dt(dt: str) -> str:
    """分型 datetime 形如 '20260821' → '2026-08-21'。"""
    dt = str(dt)
    if len(dt) == 8 and dt.isdigit():
        return f"{dt[0:4]}-{dt[4:6]}-{dt[6:8]}"
    return dt


def _pick_latest_fractal(fractals: list[dict], end_date: str, lookback_days: int) -> dict | None:
    """在回看窗口内，取离 end_date 最近的一个分型（顶/底各取一个用于对照）。

    返回 dict: {'top': {...}|None, 'bottom': {...}|None, 'latest': {...}|None}
    """
    # 回看窗口下界（字符串比较，datetime 为 YYYYMMDD 或 YYYY-MM-DD 归一）
    def _norm(d: str) -> str:
        return str(d).replace("-", "").replace("/", "")

    lower = _norm(
        (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
    )
    upper = _norm(end_date)

    in_window = [
        f for f in fractals
        if lower <= _norm(f["datetime"]) <= upper
    ]
    top = next((f for f in reversed(in_window) if f["type"] == "top"), None)
    bottom = next((f for f in reversed(in_window) if f["type"] == "bottom"), None)
    latest = None
    candidates = [f for f in (top, bottom) if f]
    if candidates:
        latest = max(candidates, key=lambda f: _norm(f["datetime"]))
    return {"top": top, "bottom": bottom, "latest": latest}


def _fractal_to_record(f: dict | None) -> dict | None:
    if not f:
        return None
    return {
        "type": f["type"],
        "datetime": _fmt_dt(f["datetime"]),
        "price": f["high"] if f["type"] == "top" else f["low"],
    }


def _norm_date(d: object) -> str | None:
    """把分型 datetime 归一化为 YYYY-MM-DD（兼容连写/带横线/Timestamp）。"""
    if d is None:
        return None
    s = str(d)[:10]
    if "-" in s or "/" in s:
        return s[:10]
    if s.isdigit() and len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def _build_card(code: str, recent_two: list[dict]) -> str:
    """分型卡片（Markdown）：仅列出最近两次分型的「类型 + 生成时间」。

    不比较是否新分型，只朴素展示最近两次分型，供快速浏览。
    recent_two 按时间升序，最后一条为最近一次分型。
    """
    name = get_stock_name(code)
    lines = [f"### 📌 {name} · 收盘分型监控"]

    if not recent_two:
        lines.append("> 暂无分型数据")
        return "\n".join(lines)

    for i, f in enumerate(recent_two):
        if not f:
            continue
        label = "顶分型" if f.get("type") == "top" else "底分型"
        d = _norm_date(f.get("datetime"))
        tag = "最近一次" if i == len(recent_two) - 1 else "上一次"
        lines.append(f"- **{tag}分型**：{label}　生成时间：{d}")

    return "\n".join(lines)


def _is_trading_day(date: datetime) -> bool:
    """判定某天是否为交易日（含法定节假日，查本地交易日历，兜底 weekday）。"""
    from src.data.trade_calendar import is_trading_day as _cal_is_td

    return _cal_is_td(date.strftime("%Y-%m-%d"))


def run_monitor(force: bool = False, enable_notify: bool = True) -> dict:
    """执行一次完整监控。

    Args:
        force: 为 True 时跳过非交易日判定（供 Web 按钮手动触发，想随时跑）。
        enable_notify: 为 True 时按配置推送渠道；为 False 时只取数+分析+
            组装 items，不触达任何推送渠道（用于测试/打印 AI payload 等场景）。
    Returns:
        {
            "ran": bool,            # 是否实际执行
            "skipped_reason": str,  # 跳过原因（ran=False 时）
            "scanned": int,         # 扫描标的数
            "new_fractal": int,     # 出现新分型标的数
            "cards": list[str],     # 各标的消息卡片
            "messages": list[str],  # 实际推送的完整消息（含表头）
        }
    """
    now = datetime.now()
    if not force and not _is_trading_day(now):
        logger.info("[monitor] 跳过：非交易日（周末/节假日），date=%s", now.strftime("%Y-%m-%d"))
        return {
            "ran": False,
            "skipped_reason": "非交易日（周末/节假日），跳过",
            "scanned": 0,
            "new_fractal": 0,
            "cards": [],
            "messages": [],
            "items": [],
        }

    codes = settings.MONITOR_CODES
    # 支持纯数字标的（如 "600519"），统一标准化为标准格式（600519.SH），
    # 并去重（避免 600519 与 600519.SH 重复扫描）。
    from src.utils.common import normalize_stock_code

    norm_codes = []
    seen = set()
    for raw in codes:
        nc = normalize_stock_code(raw)
        if nc not in seen:
            seen.add(nc)
            norm_codes.append(nc)
    codes = norm_codes
    if not codes:
        logger.warning("[monitor] 跳过：未配置 MONITOR_CODES，无监控标的")
        return {
            "ran": False,
            "skipped_reason": "未配置 MONITOR_CODES，无监控标的",
            "scanned": 0,
            "new_fractal": 0,
            "cards": [],
            "messages": [],
            "items": [],
        }

    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=settings.NOTIFY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    logger.info(
        "[monitor] 启动 | 标的=%d | 区间=%s~%s | 触发=%s",
        len(codes), start_date, end_date, "手动" if force else "定时",
    )

    fetcher = StockDBFetcher()
    cards: list[str] = []
    items: list[dict] = []  # 供 AI 研判使用：每条标的的 summary / df / 分型判定
    new_count = 0
    scanned = 0

    for code in codes:
        scanned += 1
        try:
            df = load_or_fetch(
                code, start_date, end_date, fetcher,
                data_type="daily", frequency="daily", source="stockdb",
            )
            if df is None or df.empty:
                logger.warning("[monitor] %s 取数为空，跳过", code)
                cards.append(f"### 📌 {code}\n> ⚠️ 取数为空，跳过")
                continue

            _, summary = analyze(df)
            logger.info(
                "[monitor] %s | K线=%d | 分型=%d | 笔=%d",
                code, len(df),
                summary.get("fractal_count") or 0,
                summary.get("segment_count") or 0,
            )
            fractals = summary.get("fractals", [])
            picked = _pick_latest_fractal(fractals, end_date, settings.NOTIFY_LOOKBACK_DAYS)
            current_rec = _fractal_to_record(picked.get("latest"))

            # 判定"新分型"：必须是「执行当天」形成的分型，且与上次快照不同（去重）。
            # 仅"回看窗口内最新分型 != 上次快照"不足以证明今天出现新分型——
            # 该分型可能早于今天形成，会在后续每天都误判为"新"。
            state = _load_state(code)
            last_rec = state.get("last_fractal")
            formed_today = current_rec is not None and current_rec["datetime"] == end_date
            is_new = formed_today and (
                last_rec is None
                or current_rec["datetime"] != last_rec.get("datetime")
                or current_rec["type"] != last_rec.get("type")
            )
            logger.info(
                "[monitor] %s 分型判定 | 窗口最新分型=%s@%s | 执行日=%s | 形成于今日=%s | 上次快照=%s | 新=%s",
                code,
                current_rec["type"] if current_rec else None,
                current_rec["datetime"] if current_rec else None,
                end_date, formed_today,
                last_rec, is_new,
            )

            if is_new:
                new_count += 1
                logger.info(
                    "[monitor] %s 发现新分型 | 类型=%s | 日期=%s | 价格=%.2f",
                    code, current_rec["type"], current_rec["datetime"], current_rec["price"],
                )
                # 更新快照（记录本次分型）
                _save_state(code, {
                    "last_fractal": current_rec,
                    "updated_at": end_date,
                })

            # 卡片只列最近两次分型（类型 + 生成时间），不比较是否新分型
            recent_two = [r for r in (_fractal_to_record(f) for f in fractals[-2:]) if r]
            card = _build_card(code, recent_two)

            # 收集 AI 研判所需数据（df 转 dict，取最后 60 根足矣切片）
            _window_cols = ["datetime", "open", "high", "low", "close", "volume", "amount"]
            _df_window = (
                df[_window_cols].tail(60).copy()
                if all(c in df.columns for c in _window_cols) else df.tail(60)
            )
            _df_records = [
                {
                    "date": str(r.get("datetime"))[:10],
                    "open": r.get("open"),
                    "high": r.get("high"),
                    "low": r.get("low"),
                    "close": r.get("close"),
                    "volume": r.get("volume"),
                    "amount": r.get("amount"),
                }
                for _, r in _df_window.iterrows()
            ]
            items.append({
                "code": code,
                "name": get_stock_name(code),
                "is_new": is_new,
                "current_rec": current_rec,
                "last_rec": last_rec,
                "summary": summary,
                "df_window": _df_records,
            })

            cards.append(card)
        except Exception as e:  # 单标的异常不影响其他标的
            cards.append(f"### 📌 {code}\n> ❌ 处理异常：{e}")

    # 组装完整消息并推送
    messages: list[str] = []
    if cards:
        header = (
            f"# 🔔 缠论收盘分型监控\n"
            f"> 日期：{end_date}（{'手动触发' if force else '定时任务'}）\n"
            f"> 扫描 {scanned} 只标的\n"
            f"---\n"
        )
        body = "\n\n".join(cards)
        full_msg = header + body
        messages.append(full_msg)

        notifiers: list[Notifier] = get_notifiers() if enable_notify else []
        if notifiers:
            logger.info(
                "[monitor] 推送 | 渠道=%d | 扫描=%d | 新分型=%d",
                len(notifiers), scanned, new_count,
            )
            # full_msg 已含标题/日期/扫描摘要 + 模板B卡片，整段作为 content 推送；
            # title 仅作消息标题（飞书/企微可能展示为加粗前缀）
            for notifier in notifiers:
                _ch = type(notifier).__name__
                try:
                    _ok = notifier.send("缠论收盘分型监控", full_msg)
                    logger.info(
                        "[monitor] 推送结果 | 渠道=%s | 结果=%s",
                        _ch, "成功" if _ok else "失败",
                    )
                except Exception as _e:
                    logger.error("[monitor] 推送异常 | 渠道=%s | 错误=%s", _ch, _e)
        else:
            logger.warning("[monitor] 未配置推送渠道，仅本地打印 | 扫描=%d | 新分型=%d", scanned, new_count)
            # 未配置渠道：本地打印，便于调试（Windows gbk 控制台需安全编码）
            _safe_print(full_msg)

    return {
        "ran": True,
        "skipped_reason": "",
        "scanned": scanned,
        "new_fractal": new_count,
        "cards": cards,
        "messages": messages,
        "items": items,
    }


def main() -> None:
    res = run_monitor(force=False)
    if not res["ran"]:
        _safe_print(f"[monitor] 跳过：{res['skipped_reason']}")
        return
    _safe_print(
        f"[monitor] 完成：扫描 {res['scanned']} 只，"
        f"新分型 {res['new_fractal']} 只"
    )
    if not res["messages"]:
        _safe_print("[monitor] 本次无推送内容")


if __name__ == "__main__":
    main()
