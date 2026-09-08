"""web/app.py - 缠论K线分析工具 Web 界面（Phase 5 · Step 5-2，改造后新入口）

迁移自 project_backup/app/main.py，改造点（对齐《分步执行清单》Step 5-2）：
  1. import 路径：引用 src/cli/runner、src/config/settings、src/utils/logger、
     src/utils/common、src/visual/plotly_viz、web/styles；
  2. 数据源：唯一使用 settings.DEFAULT_PARAMS["data_source"]（stockdb，本地服务，
     免 token 即可用）；前端数据源下拉框仅展示 StockDB。
  3. 布局美化：标题+简介+固定免责提示栏；参数控件分组（标的组/周期组）；
     按钮整行宽度；结果区 st.success/warning/error；图表自适应宽度；
  4. 分析仅在点击「🚀 开始分析」按钮时触发；切换日线/分钟线、时间区间、显示选项
     等参数不再自动重跑（结果存入 session_state.analysis，供图表重绘与 AI 入口复用）；
  5. @st.cache_data 缓存保留在 web 侧，不迁移到 runner；
  6. 原控件/输出项保留：股票代码/日期/数据类型/分钟周期；
  7. 港股输入：stockdb 不支持港股，输入港股代码时主动提示并中断；
  8. 反馈性 print 替换为 logger（fetcher/算法内 print 不动）。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta

# 添加项目根目录到路径以导入 src / web 模块（streamlit run 下脚本目录非仓库根）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.cli.runner import fetch_data, analyze
from src.config import settings
from src.utils.common import get_default_end_date, get_market_type, normalize_stock_code
from src.utils.logger import get_logger, get_recent_logs, read_log_file
from src.visual.plotly_viz import plotly_chanlun_visualization, plotly_daily_candlestick
from scripts.monitor_job import run_monitor
from src.data.stock_names import get_stock_name, load_stock_names
from web.auth import check_password
from web.styles import inject_styles, inject_ai_fab_js
from src.ai.review import build_single_payload, call_ai, parse_review

logger = get_logger(__name__)

# 页面配置
st.set_page_config(**settings.PAGE_CONFIG)

# 注入全局样式
inject_styles()

# 登录守卫：未通过认证只渲染登录框并 return，不触发任何数据获取
if not check_password():
    st.stop()


def _boot_diagnostics():
    """启动自检：在侧栏展示当前环境配置状态，明确 .env 是否已就绪。

    仅渲染一次（session_state 去重）。不阻塞启动——唯一数据源为本地 stockdb，
    无需 token 即可用。
    """
    if st.session_state.get("_boot_diag_done"):
        return
    st.session_state._boot_diag_done = True

    with st.sidebar:
        st.caption("⚙️ 运行环境")
        # 认证
        if settings.AUTH_ENABLED:
            st.success("🔐 登录守卫：已开启")
        else:
            st.warning("🔓 登录守卫：已关闭（仅限本地/内网）")
        # 数据源就绪情况
        st.markdown(
            f"- 数据源：**{settings.DEFAULT_PARAMS['data_source']}**（本地服务，免 token）"
        )
        logger.info(
            "启动自检 | 认证=%s | 默认源=%s",
            settings.AUTH_ENABLED,
            settings.DEFAULT_PARAMS["data_source"],
        )


_boot_diagnostics()


@st.cache_data(ttl=settings.CACHE_TTL)
def cached_analysis(stock_code, start_date, end_date, data_type, frequency, data_source):
    """缓存的分析函数（缓存保留在 web 侧，不迁移到 runner）。

    数据源统一为 stockdb，走 runner.fetch_data + runner.analyze。

    返回 (result, summary, source_meta)：
      source_meta 在函数体执行时捕获本次取数的真实来源（远程/本地命中），
      随缓存一起返回，避免 @st.cache_data 命中时不执行函数体导致读到上一次
      残留的全局变量（kline_cache.last_source / runner.last_data_source）。
    """
    import src.cli.runner as _runner
    from src.data import kline_cache as _kc

    df = fetch_data(
        stock_code, start_date, end_date, data_type=data_type,
        frequency=frequency, data_source=data_source,
    )
    source_meta = {
        "source": _runner.last_data_source,           # 固定为 "stockdb"
        "cache_hit": _kc.last_source == "local",      # 命中本地缓存（未发起远程请求）
        "local_count": _kc.last_local_count,          # 本次返回中来自本地缓存的条数
        "remote_count": _kc.last_remote_count,        # 本次返回中来自远程新增查询的条数
    }
    result, summary = analyze(df)
    return result, summary, source_meta


# 日志视图中所有功能模块（component）标签，供前端筛选
_LOG_COMPONENTS = ["WEB", "AI", "RUNNER", "KLINE_CACHE", "STOCKDB", "TRADE_CAL", "MONITOR", "CHANLUN", "SYSTEM"]

# 级别颜色映射（Streamlit markdown 内联徽章）
_LEVEL_BADGE = {
    "DEBUG": "⚪",
    "INFO": "🔵",
    "WARNING": "🟡",
    "ERROR": "🔴",
}


def _render_log_view():
    """日志视图：按功能模块（component）分类筛选展示全范围日志。

    支持：
      - 来源切换：内存缓冲（本进程）/ 日志文件（含 monitor 独立进程）
      - component 多选筛选
      - 级别阈值 + 关键词搜索
      - 自动刷新（可选）
    """
    st.markdown("### 📋 运行日志")
    st.caption("按功能模块分类筛选；「日志文件」来源可查看历史持久化日志。")

    # 筛选控件
    col_src, col_comp, col_lvl, col_kw = st.columns([1.2, 2.5, 1, 1.8])
    with col_src:
        source = st.selectbox(
            "来源",
            options=["内存缓冲", "日志文件"],
            index=0,
            help="内存缓冲=本 Web 进程产生的日志；日志文件=持久化的历史日志",
        )
    with col_comp:
        selected_components = st.multiselect(
            "功能模块",
            options=_LOG_COMPONENTS,
            default=_LOG_COMPONENTS,
            help="按功能模块筛选（WEB/RUNNER/缓存/数据源/交易日历/监控/算法等）",
        )
    with col_lvl:
        level = st.selectbox("最低级别", options=["DEBUG", "INFO", "WARNING", "ERROR"], index=1)
    with col_kw:
        keyword = st.text_input("关键词", placeholder="消息包含…", label_visibility="collapsed")

    col_auto, col_limit = st.columns([1, 1])
    with col_auto:
        auto_refresh = st.checkbox("自动刷新(3s)", value=False)
    with col_limit:
        limit = st.number_input("条数上限", min_value=50, max_value=5000, value=500, step=50)

    # 读取日志
    if source == "内存缓冲":
        logs = get_recent_logs(
            limit=limit,
            components=selected_components or None,
            level=level,
            keyword=keyword.strip(),
        )
    else:
        logs = read_log_file(
            limit=limit,
            components=selected_components or None,
            level=level,
            keyword=keyword.strip(),
        )

    if not logs:
        st.info("暂无符合条件的日志记录。")
        return

    st.caption(f"共 {len(logs)} 条")

    # 展示：时间 + 级别徽章 + component + message（+ 可展开 context）
    for entry in logs:
        ts = entry.get("ts", "")
        lvl = entry.get("level", "INFO")
        comp = entry.get("component", "SYSTEM")
        msg = entry.get("message", "")
        ctx = entry.get("context")
        badge = _LEVEL_BADGE.get(lvl, "⚪")
        header = f"`{ts}` {badge} **{comp}** · {msg}"
        if ctx:
            with st.expander(header, expanded=False):
                st.json(ctx)
        else:
            st.markdown(header)

    if auto_refresh:
        import time
        time.sleep(3)
        st.rerun()


def main():
    """主函数"""
    # 标题 + 简介
    st.markdown(
        '<div class="chanlun-title">📊 缠论K线分析工具</div>', unsafe_allow_html=True
    )
    st.markdown(
        '<div class="chanlun-subtitle">基于本地 StockDB（免 token、全本地）· 分型 + 笔识别（仅供学习研究）</div>',
        unsafe_allow_html=True,
    )
    # 固定免责提示栏
    st.markdown(
        '<div class="chanlun-disclaimer">⚠️ 免责声明：本工具仅为缠论算法学习与研究的工程化尝试，'
        "不构成任何投资建议。投资有风险，入市需谨慎。数据源为本地 StockDB（支持 A股/ETF/指数，日线+分钟线，前/后复权）。"
        "</div>",
        unsafe_allow_html=True,
    )

    # 侧边栏参数配置
    with st.sidebar:
        st.markdown("### ⚙️ 参数配置")

        # 数据源：唯一为 settings 中的 stockdb（本地服务）。
        with st.container(border=True):
            st.markdown("**🔌 数据源**")
            data_source = st.selectbox(
                "数据源",
                options=list(settings.DATA_SOURCES.keys()),
                index=list(settings.DATA_SOURCES.keys()).index(
                    settings.DEFAULT_PARAMS["data_source"]
                ),
                format_func=lambda x: str(settings.DATA_SOURCES[x]["name"]),
                help="本地 stockdb 服务，免 token、全本地、低延迟，支持日线与分钟线",
            )

        # 标的组
        with st.container(border=True):
            st.markdown("**📌 标的**")
            stock_code_input = st.text_input(
                "股票代码",
                value=settings.DEFAULT_CODE,
                help="支持格式: 600000, 600000.SH, 510300, 000300（暂不支持港股）",
            )

        # 周期组
        with st.container(border=True):
            st.markdown("**📅 周期**")
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input(
                    "开始日期",
                    value=(datetime.now() - timedelta(days=1000)).date(),
                    help="数据获取的起始日期（默认当天往前 500 天）",
                )
            with col2:
                end_date = st.date_input(
                    "结束日期",
                    value=get_default_end_date(),
                    help="数据获取的结束日期",
                )

            # 数据类型（StockDB 源同时支持日线与分钟线）
            data_type = st.radio(
                "数据类型",
                ["daily", "minute"],
                format_func=lambda x: "日线" if x == "daily" else "分钟线",
                horizontal=True,
            )
            frequency = settings.DEFAULT_FREQUENCY
            if data_type == "minute":
                frequency = st.selectbox(
                    "分钟周期",
                    settings.MINUTE_FREQUENCIES,
                    index=settings.DEFAULT_MINUTE_FREQ_INDEX,
                    help="选择分钟K线的周期",
                )

        # 显示选项（v5：日线蜡烛图对照面板开关）
        with st.container(border=True):
            st.markdown("**📊 显示选项**")
            show_raw_candle = st.checkbox(
                "显示日线蜡烛图(原始)",
                value=True,
                help="在主图上方展示纯日线蜡烛图，用于与缠论分析图对照",
            )
            show_ma = st.checkbox(
                "蜡烛图叠加均线 (MA5/10/20/30/60)",
                value=True,
                help="在原始蜡烛图上叠加 MA5/10/20/30/60 均线（基于区间收盘价）",
            )

        # 每日收盘监控：手动立即触发（复用 scripts/monitor_job.run_monitor）
        with st.container(border=True):
            st.markdown("**🔔 每日收盘监控**")
            # 拉取全市场标的字典并缓存到本地（cache/stock_names.json）
            # 注：stockdb 名称接口接入前，该按钮暂不可用（名称统一从本地缓存读取）
            pull_button = st.button(
                "📥 拉取全量标的",
                use_container_width=True,
                help="待 stockdb 名称接口接入后开放；当前名称统一从本地缓存读取",
                disabled=True,
            )
            if pull_button:
                with st.spinner("🔄 正在拉取全市场标的..."):
                    try:
                        _t0 = datetime.now()
                        names = load_stock_names(force_refresh=True)
                        _cost = (datetime.now() - _t0).total_seconds()
                        logger.info(
                            "拉取全量标的完成 | 数量=%d | 耗时=%.2fs | 写入=cache/stock_names.json",
                            len(names), _cost,
                        )
                        st.success(f"✅ 已拉取 {len(names)} 只标的并保存到本地")
                    except Exception as e:
                        logger.error("拉取标的失败: %s", e)
                        st.error(f"❌ 拉取失败: {str(e)}")

            monitor_button = st.button(
                "🚀 立即执行收盘监控",
                use_container_width=True,
                help="手动触发一次完整的收盘分型监控（随时可跑）",
            )
            if monitor_button:
                with st.spinner("🔄 正在执行收盘监控..."):
                    try:
                        res = run_monitor(force=True)
                        if not res["ran"]:
                            st.warning(f"⚠️ 未执行：{res['skipped_reason']}")
                        elif res["new_fractal"] > 0:
                            st.success(
                                f"✅ 监控完成：扫描 {res['scanned']} 只标的，"
                                f"{res['new_fractal']} 只出现新分型（已推送）"
                            )
                        else:
                            st.warning("⚠️ 监控完成，本次未检测到新分型")
                        if res["messages"]:
                            with st.expander("查看推送内容"):
                                for msg in res["messages"]:
                                    st.markdown(msg)
                    except Exception as e:
                        logger.error("监控按钮执行失败: %s", e)
                        st.error(f"❌ 监控执行失败: {str(e)}")

        # 分析按钮
        analyze_button = st.button("🚀 开始分析", use_container_width=True)

        # 视图切换：分析 / 日志
        st.divider()
        view = st.radio(
            "视图",
            options=["分析", "日志"],
            index=0,
            horizontal=True,
            help="切换到「日志」可查看全范围分类日志（按功能模块筛选）",
        )

    # 日志视图
    if view == "日志":
        _render_log_view()
        return

    # 主内容区
    # 仅在点击「🚀 开始分析」时触发取数 + 分析；切换日线/分钟线、时间区间、
    # 显示选项等参数均不会自动重跑。分析成功后结果存入 st.session_state.analysis，
    # 下方渲染段每次脚本重跑都据此重绘（保证显示选项切换能即时刷新图表）。
    if analyze_button:
        # 标准化股票代码
        stock_code = normalize_stock_code(stock_code_input)

        # 参数校验
        if start_date > end_date:
            st.error("❌ 开始日期不能晚于结束日期!")
            return

        # 港股提示：stockdb 不支持港股，主动提示并中断
        if get_market_type(stock_code) == "hk":
            st.warning("❌ StockDB 数据源暂不支持港股，请使用 A股/ETF/指数代码!")
            return

        # 分钟线提示：仅未声明支持分钟线的数据源才拦截（当前 StockDB 支持分钟线）
        _MINUTE_SUPPORTED = {"stockdb"}  # 支持分钟线的数据源集合（与 settings.DATA_SOURCES 同步维护）
        if data_type != "daily" and data_source not in _MINUTE_SUPPORTED:
            st.warning(
                f"⚠️ {data_source} 数据源当前仅支持日线，分钟线请切换数据源为 StockDB 或选择「日线」!"
            )
            return

        # 显示加载状态
        with st.spinner(f"🔄 正在分析 {stock_code}..."):
            try:
                _t0 = datetime.now()
                logger.info(
                    "开始分析 %s | 区间=%s~%s | 数据源=%s | 类型=%s",
                    stock_code, start_date, end_date, data_source, data_type,
                )
                # 调用缓存的分析函数（web 侧缓存，含 fetch_data + analyze）
                result, summary, source_meta = cached_analysis(
                    stock_code,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                    data_type,
                    frequency,
                    data_source,
                )
                _cost = (datetime.now() - _t0).total_seconds()

                # 结果摘要
                stock_name = get_stock_name(stock_code)
                logger.info(
                    "分析完成 %s | 来源=%s%s | 耗时=%.2fs | K线=%d | 分型=%s | 笔=%s",
                    stock_code,
                    source_meta.get("source"),
                    "（本地缓存）" if source_meta.get("cache_hit") else "（远程）",
                    _cost,
                    len(result),
                    summary.get("fractal_count"),
                    summary.get("segment_count"),
                )
                st.success(
                    f"✅ 分析完成：{stock_name} · "
                    f"分型 {summary.get('fractal_count', '?')} 个 / "
                    f"笔 {summary.get('segment_count', '?')} 个"
                )

                # 数据来源提示（本地缓存命中 / 远程查询 StockDB）
                # source_meta 随缓存返回，缓存命中时也是本次分析的真实来源
                _src = source_meta.get("source", "stockdb")
                _cache_hit = source_meta.get("cache_hit", False)
                _local_count = int(source_meta.get("local_count", 0) or 0)
                _remote_count = int(source_meta.get("remote_count", 0) or 0)
                _label = {"stockdb": "StockDB"}.get(_src, _src)
                # 返回总条数 = 本地命中 + 远程新增
                _total_count = _local_count + _remote_count
                if _cache_hit:
                    st.info(
                        f"📁 数据来源：本地缓存（{_label}，未发起远程请求）｜"
                        f"共 {_total_count} 条（本地 {_local_count} 条 · 新增 0 条）"
                    )
                else:
                    st.info(
                        f"🌐 数据来源：实时查询 {_label}｜"
                        f"共 {_total_count} 条（本地 {_local_count} 条 · 新增 {_remote_count} 条）"
                    )

                # 保存本次分析结果到 session_state：供下方渲染段重绘，
                # 以及后续「AI 深度分析」悬浮入口复用（无需再次取数）。
                st.session_state.analysis = {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "data_type": data_type,
                    "frequency": frequency,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "result": result,
                    "summary": summary,
                    "source_meta": source_meta,
                }
                # AI 深度分析上下文（供悬浮按钮复用，rerun 安全、无条件写入）
                # kline_tail：以「最新分型」为起点，含分型本身及其后的 K 线与成交量，
                # 最多 AI_KLINE_WINDOW 根，确保 AI 看到分型确认后的量价演化（更精准）。
                # 定位用分型 index 标签（.loc 抗 trimming 偏移）；异常则回退到尾部窗口。
                _ai_fractals = summary.get("fractals") or []
                _kline_tail = result.tail(settings.AI_KLINE_WINDOW)
                if _ai_fractals:
                    try:
                        _latest_idx = _ai_fractals[-1]["index"]
                        _post = result.loc[_latest_idx:]
                        if len(_post) > 0:
                            _kline_tail = _post.iloc[: settings.AI_KLINE_WINDOW]
                    except Exception:
                        _kline_tail = result.tail(settings.AI_KLINE_WINDOW)
                st.session_state.ai_ctx = {
                    "summary": summary,
                    "kline_tail": _kline_tail,
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "data_type": data_type,
                    "frequency": frequency,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                }
            except Exception as e:
                logger.error("分析失败 %s: %s", stock_code, e)
                st.error(f"❌ 分析失败: {str(e)}")

    # 结果渲染：每次脚本重跑都执行（使显示选项切换即时刷新图表），
    # 不触发任何取数 / 分析；仅当已存在分析结果时绘制。
    _analysis = st.session_state.get("analysis")
    if _analysis is not None:
        # 当前所选参数与已分析结果不一致时提示需重新点击分析（不自动重跑）
        _cur_freq = frequency if data_type == "minute" else _analysis.get("frequency", "")
        if (
            data_type != _analysis["data_type"]
            or start_date.strftime("%Y-%m-%d") != _analysis["start_date"]
            or end_date.strftime("%Y-%m-%d") != _analysis["end_date"]
            or _cur_freq != _analysis.get("frequency", "")
        ):
            _period = "日线" if _analysis["data_type"] == "daily" else f'{_analysis.get("frequency", "")}分钟线'
            st.info(
                f"ℹ️ 当前展示的是上次分析（{_analysis['stock_name']} · "
                f"{_analysis['start_date']}~{_analysis['end_date']} · {_period}）的结果；"
                f"参数已变更，请点击「🚀 开始分析」刷新。"
            )

        result = _analysis["result"]
        summary = _analysis["summary"]
        source_meta = _analysis["source_meta"]
        stock_code = _analysis["stock_code"]
        stock_name = _analysis["stock_name"]
        data_type = _analysis["data_type"]
        frequency = _analysis["frequency"]

        # 生成图表
        data_type_with_freq = (
            data_type if data_type == "daily" else f"minute_{frequency}"
        )

        # 原始蜡烛图对照面板（日线 + 分钟线均支持，开关开启时展示）
        if show_raw_candle:
            _panel_title = "日线蜡烛图（原始K线）" if data_type == "daily" else f"{frequency}分钟蜡烛图（原始K线）"
            st.markdown(f"### 📈 {_panel_title}· {stock_name}")
            candle_obj = plotly_daily_candlestick(
                result, stock_code=stock_code, return_fig=True, show_ma=show_ma
            )
            if candle_obj is not None:
                # 内联 Plotly.js（不依赖外网 CDN），消除图表加载空白
                candle_html = candle_obj.to_html(
                    include_plotlyjs=True, full_html=False
                )
                # 渲染前占位提示，避免 iframe 上屏前的视觉空白
                _ph = st.empty()
                _ph.info("⏳ 正在渲染蜡烛图...")
                st.components.v1.html(
                    candle_html, height=620, scrolling=True
                )
                _ph.empty()
            else:
                st.warning("⚠️ 原始蜡烛图生成失败")

        chart_obj = plotly_chanlun_visualization(
            result,
            start_idx=0,
            bars_to_show=len(result),
            data_type=data_type_with_freq,
            return_fig=True,
            stock_code=stock_code,
        )

        if chart_obj is not None:
            # 每个 st.components.v1.html 都是独立 iframe，无法复用另一张图的库，
            # 故各自内联 Plotly.js（去掉外网 CDN 依赖，消除加载空白/报错）
            html_string = chart_obj.to_html(
                include_plotlyjs=True, full_html=False
            )
            _ph2 = st.empty()
            _ph2.info("⏳ 正在渲染缠论分析图...")
            st.components.v1.html(
                html_string, height=settings.CHART_HEIGHT, scrolling=True
            )
            _ph2.empty()
        else:
            st.error("❌ 图表生成失败!")

    # AI 深度分析悬浮按钮 + 弹窗（rerun 安全：主流程每次重跑都执行）
    _render_ai_fab()


@st.dialog("🤖 AI 深度分析", width="large", dismissible=False)
def _ai_dialog_body():
    """AI 深度分析弹窗：展示发送内容（含逐项解释）与返回结果。"""
    ctx = st.session_state.get("ai_ctx")

    if not settings.AI_ENABLED:
        st.warning(
            "⚠️ AI 未开启：请在 .env 配置 AI_ENABLED=true 与 "
            "AI_BASE_URL/AI_MODEL/AI_API_KEY 后重启服务"
        )
        _dialog_footer()
        return
    if ctx is None:
        st.info("👋 请先在左侧点击「🚀 开始分析」，取得分析结果后再深度分析")
        _dialog_footer()
        return

    # 上下文变化 / 强制重算 → 失效缓存，避免重复烧 token
    if st.session_state.get("ai_dialog_src") is not ctx:
        st.session_state.ai_dialog_src = ctx
        st.session_state.pop("ai_dialog_payload", None)
        st.session_state.pop("ai_dialog_review", None)
    if st.session_state.get("_ai_force_recompute"):
        st.session_state.pop("ai_dialog_payload", None)
        st.session_state.pop("ai_dialog_review", None)
        st.session_state.pop("_ai_force_recompute", None)

    if "ai_dialog_payload" not in st.session_state:
        # 整个「组装 → 发送 → 等待返回 → 解析」都在同一 st.status 内完成，
        # 保证最终状态能更新为「分析完成 + 耗时」，而不是停在「等待模型返回」。
        with st.status("🔄 正在组装并发送 AI 请求…", expanded=True) as status:
            payload = build_single_payload(
                ctx["kline_tail"], ctx["summary"],
                ctx["stock_code"], ctx["stock_name"],
                data_type=ctx["data_type"], frequency=ctx["frequency"],
            )
            if not payload:
                status.update(label="未识别到分型", state="error")
                st.warning("该区间未识别出分型，无需 AI 研判")
                _dialog_footer()
                return
            status.update(label="✅ 已发送，等待模型返回…")
            _t0 = time.perf_counter()
            try:
                resp = call_ai(payload)
                review = parse_review(resp)
            except Exception as e:
                status.update(label="❌ AI 研判失败", state="error")
                logger.error("AI 深度分析失败: %s", e)
                st.error(f"⚠️ AI 研判失败：{e}")
                _dialog_footer()
                return
            _cost = time.perf_counter() - _t0
            status.update(label=f"✅ 分析完成，耗时 {_cost:.2f}s", state="complete")
        st.session_state.ai_dialog_payload = payload
        st.session_state.ai_dialog_review = review
        st.session_state.ai_result = review  # 供弹窗关闭后的折叠区回看

    _render_sent_content(st.session_state.ai_dialog_payload, ctx)
    _render_review(st.session_state.ai_dialog_review, ctx)
    _dialog_footer()


def _render_sent_content(payload: dict, ctx: dict) -> None:
    """展示发送给 AI 的内容，并逐项解释其含义。"""
    st.subheader("📤 发送给大模型的内容")
    meta = payload.get("meta", {})
    ctx_d = payload.get("context", {})
    kline = ctx_d.get("kline_window", [])
    sig = (payload.get("signals") or [{}])[0]
    fr = sig.get("recent_fractals", [])
    seg = sig.get("recent_segments", [])
    period = "日线" if meta.get("data_type") == "daily" else f"{meta.get('frequency')}分钟线"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("周期", period)
    c2.metric("K线窗口", f"{len(kline)} 根")
    c3.metric("最近分型", f"{len(fr)} 个")
    c4.metric("最近笔段", f"{len(seg)} 笔")
    _mf_days = sum(1 for r in kline if r.get("flow"))
    c5.metric("资金流", f"{_mf_days} 日" if meta.get("include_money_flow") else "未附带")

    st.markdown("**内容构成说明**")
    items = [
        ("📈 量价 K 线窗口（kline_window）",
         f"共 <b>{len(kline)}</b> 根，以「最新分型」为起点（含分型本身及其后的 K 线），"
         "每根含 开/高/低/收、成交量(volume)、成交额(amount)。模型据此判断分型确认后的量价演化。"),
        ("💵 个股日资金流（flow，内嵌于每根 K 线）",
         f"窗口中 <b>{_mf_days}</b> 根附带资金流（仅查询最新分型当日及其之后的交易日）："
         "主力净流入(main_net)、超大/大/中/小单净流入(jumbo/big/mid/small_net)"
         "及主力/散户买卖额；单位元，正=流入、负=流出。"
         "结合主力方向可判断分型确认时资金是否配合。无数据的交易日 flow 为 null；"
         "stockdb 取数失败时自动跳过，不影响本次研判。"),
        ("💰 最新收盘（last_close）",
         f"窗口最后一根收盘价：<b>{ctx_d.get('last_close')}</b>"),
        ("🔺 最近分型序列（recent_fractals）",
         f"最近 <b>{len(fr)}</b> 个分型，含 顶/底类型、高低价、时间，供模型自行锁定最关键分型。"),
        ("📏 最近笔段（recent_segments）",
         f"最近 <b>{len(seg)}</b> 笔，含方向(up/down)，刻画当前笔的延伸。"),
        ("⚙️ 周期与配置（meta）",
         f"{period}；含资金流：{'是' if meta.get('include_money_flow') else '否'}。"
         "本项目不做基本面研判，不传任何基本面数据。"),
    ]
    for title, desc in items:
        st.markdown(
            f'<div class="ai-card"><div class="ai-card-title">{title}</div>'
            f'<div class="ai-card-body">{desc}</div></div>',
            unsafe_allow_html=True,
        )

    with st.expander("🔍 查看完整发送 JSON（技术细节）"):
        st.json(payload)


def _render_review(review: dict, ctx: dict) -> None:
    """展示 AI 返回的研判结果，重点字段卡片化。"""
    st.divider()
    st.subheader("📥 AI 返回结果")
    _period = "日线" if ctx.get("data_type") == "daily" else f"{ctx.get('frequency')}分钟线"
    st.caption(
        f"研判对象：{ctx.get('stock_name')}（{ctx.get('stock_code')}）· "
        f"区间 {ctx.get('start_date')} ~ {ctx.get('end_date')} · {_period}"
    )
    # 模型自行锁定的关注分型（focus_fractal）
    _focus = review.get("focus_fractal") or {}
    if _focus:
        _ftype = {"top": "顶分型", "bottom": "底分型"}.get(
            str(_focus.get("type", "")).lower(), _focus.get("type", "")
        )
        st.markdown(
            '<div class="ai-card ai-card-info"><div class="ai-card-title">🎯 模型关注的分型</div>'
            f'<div class="ai-card-body">生成时间 <b>{_focus.get("datetime", "-")}</b>'
            f' · <b>{_ftype}</b><br/>{_focus.get("reason", "")}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f"**可信性**：{_ai_credibility_badge(review.get('credibility', '未知'))} &nbsp; "
        f"{review.get('credibility_reason', '')}",
        unsafe_allow_html=True,
    )
    rp = review.get("risk_points") or []
    if rp:
        st.markdown(
            '<div class="ai-card ai-card-warn"><div class="ai-card-title">⚠️ 风险点</div>'
            f'<div class="ai-card-body">{"；".join(rp)}</div></div>',
            unsafe_allow_html=True,
        )
    sug = review.get("suggestion")
    if sug:
        st.markdown(
            '<div class="ai-card ai-card-info"><div class="ai-card-title">💡 操作建议</div>'
            f'<div class="ai-card-body">{sug}（仅供参考，非买卖依据）</div></div>',
            unsafe_allow_html=True,
        )
    hr = review.get("need_human_review") or []
    if hr:
        st.warning("需人工复核：" + "；".join(hr))
    st.caption("⚠️ 本研判由大模型生成，仅供参考，不构成任何投资建议。")


def _ai_credibility_badge(cred: str) -> str:
    color = {"高": "#16a34a", "中": "#d97706", "低": "#dc2626"}.get(cred, "#6b7280")
    return (
        f'<span style="background:{color}1a;color:{color};border:1px solid {color}55;'
        f'padding:2px 10px;border-radius:999px;font-weight:600;">{cred}</span>'
    )


def _dialog_footer() -> None:
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 重新分析", key="ai_redo"):
            st.session_state._ai_force_recompute = True
            st.rerun()
    with col2:
        if st.button("关闭", key="ai_close"):
            st.session_state.ai_dialog_open = False
            st.rerun()


def _render_ai_fab():
    """渲染悬浮按钮与结果容器（rerun 安全：不放在 if analyze_button 分支内）。"""
    if st.button("🤖 AI 深度分析", key="ai_deep_analysis"):
        st.session_state.ai_dialog_open = True
    inject_ai_fab_js()  # ★ 每次 rerun 都要重新注入：Streamlit 重跑会重建 DOM

    if st.session_state.get("ai_dialog_open"):
        _ai_dialog_body()

    _render_ai_result()


def _render_ai_result():
    """弹窗关闭后，仍保留一个折叠区供快速回看上次研判。"""
    with st.expander(
        "🤖 上次 AI 研判（点击回看）",
        expanded=False,
    ):
        r = st.session_state.get("ai_result")
        if r is None:
            st.info("点击右下角「🤖 AI 深度分析」获取 AI 研判")
            return
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


if __name__ == "__main__":
    main()
