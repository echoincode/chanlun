"""web/app.py - 缠论K线分析工具 Web 界面（Phase 5 · Step 5-2，改造后新入口）

迁移自 project_backup/app/main.py，改造点（对齐《分步执行清单》Step 5-2）：
  1. import 路径：引用 src/cli/runner、src/config/settings、src/utils/logger、
     src/utils/common、src/visual/plotly_viz、web/styles；
  2. 数据源：默认使用 settings.DEFAULT_PARAMS["data_source"]（当前为 baostock，
     免费免 token 即可用）；前端开放数据源下拉框（baostock / tushare 可选），
     Tushare 需配置 TUSHARE_TOKEN 后方可取数，缺失时仅在该源被选中时报错。
  3. 布局美化：标题+简介+固定免责提示栏；参数控件分组（标的组/周期组）；
     按钮整行宽度；结果区 st.success/warning/error；图表自适应宽度；
  4. 完整保留原 session_state 自动触发逻辑（切换到上次分析过的股票时自动重跑），
     不改为"必须点击"；
  5. @st.cache_data 缓存保留在 web 侧，不迁移到 runner；
  6. 原控件/输出项保留：股票代码/日期/数据类型/分钟周期；
  7. 港股输入：仅 tushare 源不支持，baostock 支持，故默认 baostock 源无需拦截；
  8. 反馈性 print 替换为 logger（fetcher/算法内 print 不动）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

# 添加项目根目录到路径以导入 src / web 模块（streamlit run 下脚本目录非仓库根）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from src.cli.runner import fetch_data, analyze
from src.config import settings
from src.utils.common import get_default_end_date, get_market_type, normalize_stock_code
from src.utils.logger import get_logger
from src.visual.plotly_viz import plotly_chanlun_visualization, plotly_daily_candlestick
from scripts.monitor_job import run_monitor
from src.data.stock_names import get_stock_name, load_stock_names
from web.auth import check_password
from web.styles import inject_styles

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

    仅渲染一次（session_state 去重）。不阻塞启动——baostock 免费默认可用，
    Tushare 为可选增强，缺 token 时仅在该源被选中时才报错。
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
        ts_ok = bool(settings.TUSHARE_TOKEN)
        st.markdown(
            f"- 默认数据源：**{settings.DEFAULT_PARAMS['data_source']}**（免 token）"
        )
        if ts_ok:
            st.success("🟢 Tushare：已配置 TUSHARE_TOKEN")
        else:
            st.info("⚪ Tushare：未配置 TUSHARE_TOKEN（选用该源时才会提示）")
        logger.info(
            "启动自检 | 认证=%s | Tushare=%s | 默认源=%s",
            settings.AUTH_ENABLED,
            "ready" if ts_ok else "no-token",
            settings.DEFAULT_PARAMS["data_source"],
        )


_boot_diagnostics()


@st.cache_data(ttl=settings.CACHE_TTL)
def cached_analysis(stock_code, start_date, end_date, data_type, frequency, data_source):
    """缓存的分析函数（缓存保留在 web 侧，不迁移到 runner）。

    v5：数据源可切换 tushare / baostock，走 runner.fetch_data + runner.analyze。

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
        "source": _runner.last_data_source,           # "baostock" / "tushare"
        "cache_hit": _kc.last_source == "local",      # 命中本地缓存
    }
    result, summary = analyze(df)
    return result, summary, source_meta


def main():
    """主函数"""
    # 标题 + 简介
    st.markdown(
        '<div class="chanlun-title">📊 缠论K线分析工具</div>', unsafe_allow_html=True
    )
    st.markdown(
        '<div class="chanlun-subtitle">基于多数据源（Tushare / Baostock）· 分型 + 笔识别（仅供学习研究）</div>',
        unsafe_allow_html=True,
    )
    # 固定免责提示栏
    st.markdown(
        '<div class="chanlun-disclaimer">⚠️ 免责声明：本工具仅为缠论算法学习与研究的工程化尝试，'
        "不构成任何投资建议。投资有风险，入市需谨慎。数据源支持 A股/ETF/指数（Tushare、Baostock）"
        "及港股（Baostock）。"
        "</div>",
        unsafe_allow_html=True,
    )

    # 侧边栏参数配置
    with st.sidebar:
        st.markdown("### ⚙️ 参数配置")

        # 数据源：默认取自 settings（当前为 baostock），用户可切换。
        # 后端 runner.fetch_data 的 data_source 接口同时支持 tushare 与 baostock。
        with st.container(border=True):
            st.markdown("**🔌 数据源**")
            data_source = st.selectbox(
                "数据源",
                options=list(settings.DATA_SOURCES.keys()),
                index=list(settings.DATA_SOURCES.keys()).index(
                    settings.DEFAULT_PARAMS["data_source"]
                ),
                format_func=lambda x: str(settings.DATA_SOURCES[x]["name"]),
                help="Tushare 需配置 TUSHARE_TOKEN；Baostock 免费免 token，支持港股与分钟线",
            )

        # 标的组
        with st.container(border=True):
            st.markdown("**📌 标的**")
            stock_code_input = st.text_input(
                "股票代码",
                value=settings.DEFAULT_CODE,
                help="支持格式: 600000, 600000.SH, 510300, 000300；Baostock 亦支持 sh.600588 / 港股",
            )

        # 周期组
        with st.container(border=True):
            st.markdown("**📅 周期**")
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input(
                    "开始日期",
                    value=settings.DEFAULT_START_DATE,
                    help="数据获取的起始日期",
                )
            with col2:
                end_date = st.date_input(
                    "结束日期",
                    value=get_default_end_date(),
                    help="数据获取的结束日期",
                )

            # 数据类型（v4：保留控件，选分钟线时提示中断）
            data_type = st.radio(
                "数据类型",
                # 暂时注释分钟线选项，仅保留日线
                ["daily"],  # ["daily", "minute"],
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
            pull_button = st.button(
                "📥 拉取全量标的",
                use_container_width=True,
                help="从 Baostock 拉取全市场代码-名称映射并保存到本地缓存",
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
                help="手动触发一次完整的收盘分型监控（等价于定时任务，随时可跑）",
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

    # 主内容区
    # ⚠️ 完整保留原 session_state 自动触发逻辑（原 main.py 第 282 行）：
    #    若本次输入代码与上次分析过的代码相同，即使未点按钮也会自动重跑。
    if analyze_button or (
        "last_analyzed" in st.session_state
        and st.session_state.last_analyzed == stock_code_input
    ):
        if analyze_button:
            st.session_state.last_analyzed = stock_code_input

        # 标准化股票代码
        stock_code = normalize_stock_code(stock_code_input)

        # 参数校验
        if start_date > end_date:
            st.error("❌ 开始日期不能晚于结束日期!")
            return

        # 港股提示：仅 tushare 源不支持港股，主动提示并中断；baostock 支持港股
        if get_market_type(stock_code) == "hk" and data_source == "tushare":
            st.warning("❌ Tushare 数据源暂不支持港股，请切换数据源为 Baostock，或使用 A股/ETF/指数代码!")
            return

        # 分钟线提示：仅 tushare 源仅支持日线，主动提示并中断；baostock 支持分钟线
        if data_type != "daily" and data_source == "tushare":
            st.warning("⚠️ Tushare 数据源当前仅支持日线，分钟线请切换数据源为 Baostock 或选择「日线」!")
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

                # 数据来源提示（本地缓存命中 / 远程查询 Baostock / Tushare）
                # source_meta 随缓存返回，缓存命中时也是本次分析的真实来源
                _src = source_meta.get("source", "baostock")
                _cache_hit = source_meta.get("cache_hit", False)
                _label = "Tushare" if _src == "tushare" else "Baostock"
                if _cache_hit:
                    st.info(f"📁 数据来源：本地缓存（{_label}，未发起远程请求）")
                else:
                    st.info(f"🌐 数据来源：实时查询 {_label}")

                # 生成图表
                data_type_with_freq = (
                    data_type if data_type == "daily" else f"minute_{frequency}"
                )

                # v5：日线蜡烛图对照面板（仅日线 + 开关开启时展示）
                if data_type == "daily" and show_raw_candle:
                    st.markdown(f"### 📈 日线蜡烛图（原始K线）· {stock_name}")
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

            except Exception as e:
                logger.error("分析失败 %s: %s", stock_code, e)
                st.error(f"❌ 分析失败: {str(e)}")


if __name__ == "__main__":
    main()
