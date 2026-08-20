"""scripts/run_tushare.py - 缠论K线分析工具 CLI 入口（Phase 6 · Step 6-2，Tushare 薄封装）

数据源 v4 已统一为 Tushare（唯一），本脚本为新建的 Tushare CLI 薄封装，
参照原 project_backup/baostock_chanlun.py 的交互范式：
  - 保留 input() 交互式循环：输入参数 → 分析 → 图表保存/展示 → 是否继续；
  - 计算核心委托给 src/cli/runner（fetch_data + analyze），本脚本不重复实现；
  - 股票代码用 src.utils.common.normalize_stock_code 标准化（600000.SH 风格）；
  - 反馈性 print 保留给用户可见提示，诊断细节走 src.utils.logger。

【v4】Tushare 当前仅支持日线：交互中不再询问分钟线周期（与 web 侧一致，
      fetch_data 对非 daily 直接抛错）。

输出目录：项目根 results/（settings.RESULTS_DIR），与 web 侧保存目录约定一致。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

# scripts/ 在项目根下，父目录即项目根（保证 streamlit/CLI 均可导入 src / web）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cli.runner import analyze, fetch_data
from src.config import settings
from src.utils.common import get_default_end_date, normalize_stock_code
from src.utils.logger import get_logger
from src.visual.plotly_viz import plotly_chanlun_visualization

logger = get_logger(__name__)

# 结果输出目录（项目根 results/，向后兼容原脚本"脚本旁 results/"的语义）
RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), settings.RESULTS_DIR
)


def analyze_stock(stock_code, start_date, end_date):
    """分析单只股票的缠论数据（计算核心委托 runner）。

    Args:
        stock_code: 标准化 Tushare 代码（如 600000.SH）
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        (result_df, summary)；失败返回 None
    """
    print(f"📊 正在分析 {stock_code}（日线 {start_date} ~ {end_date}）...")
    try:
        data = fetch_data(stock_code, start_date, end_date, data_type="daily")
    except Exception as e:
        logger.error("获取数据失败 %s: %s", stock_code, e)
        print(f"❌ 获取数据失败: {e}")
        return None

    if data is None or data.empty:
        print(f"❌ 未能获取到 {stock_code} 的数据")
        return None

    print(f"✅ 获取数据 {len(data)} 根K线")

    # 执行缠论分析（runner.analyze 返回 (result_df, summary)，含分型/笔 list）
    result, summary = analyze(data)

    # 显示简要结果
    print(f"🎯 缠论K线: {summary.get('chanlun_count', '?')} 根")
    print(f"🔺 顶分型: {summary.get('top_fractal_count', '?')} 个")
    print(f"🔻 底分型: {summary.get('bottom_fractal_count', '?')} 个")
    print(f"✏️ 笔: {summary.get('segment_count', '?')} 个")
    return result, summary


def create_and_save_chart(result, stock_code, start_date, end_date):
    """创建图表并保存 HTML（plotly 版本，输出目录项目根 results/）。"""
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        filename = f"{stock_code}_{start_date}_{end_date}_daily.html"
        filepath = os.path.join(RESULTS_DIR, filename)

        chart_obj = plotly_chanlun_visualization(
            result,
            start_idx=0,
            bars_to_show=len(result),
            data_type="daily",
            return_fig=True,
            stock_code=stock_code,
        )
        if chart_obj is None:
            print("❌ 图表生成失败")
            return None, False

        chart_obj.write_html(filepath, include_plotlyjs="cdn")
        print(f"✅ HTML文件已保存: {filepath}")
        return chart_obj, True
    except Exception as e:
        logger.error("保存图表失败: %s", e)
        print(f"❌ HTML文件保存出错: {e}")
        return None, False


def show_chart(chart_obj):
    """显示图表（plotly 交互图，浏览器打开）"""
    if chart_obj is None:
        print("⚠️  图表对象为空")
        return
    try:
        chart_obj.show()
        print("✅ Plotly交互图表显示成功（可在浏览器中查看）")
        print("💡 功能说明：拖拽缩放 / Hover详情 / Y轴调节 / 底部成交量")
    except Exception as e:
        print(f"❌ 图表显示失败: {e}")


def get_user_input():
    """获取用户输入（交互式，直接回车使用默认值）"""
    print("\n📝 请输入分析参数（直接回车使用默认值）：")

    stock_code = input("股票代码（默认 600000）: ").strip()
    if not stock_code:
        stock_code = settings.DEFAULT_CODE

    normalized_code = normalize_stock_code(stock_code)
    if normalized_code != stock_code:
        print(f"📝 已自动识别为: {normalized_code}")
    stock_code = normalized_code

    start_date = input("开始日期（默认 2024-01-01）: ").strip()
    if not start_date:
        start_date = "2024-01-01"

    default_end_date = get_default_end_date()
    end_date = input(f"结束日期（默认 {default_end_date}）: ").strip()
    if not end_date:
        end_date = str(default_end_date)

    # 【v4】Tushare 仅支持日线，不再询问分钟周期
    return stock_code, start_date, end_date


def main():
    """主函数：交互式循环"""
    print("🎯 缠论K线分析工具（CLI）")
    print("=" * 40)
    print("💡 数据源：Tushare（唯一），当前支持 A股/ETF/指数，仅日线")
    print("💡 输入 q 可随时退出")

    while True:
        try:
            params = get_user_input()
            if params is None:
                continue

            stock_code, start_date, end_date = params

            print(f"\n{'='*50}")
            result = analyze_stock(stock_code, start_date, end_date)

            if result is not None:
                result_df, summary = result

                # 保存并展示图表
                chart_obj, save_success = create_and_save_chart(
                    result_df, stock_code, start_date, end_date
                )
                if save_success:
                    show_chart(chart_obj)

            # 询问是否继续
            continue_choice = (
                input(f"\n{'='*50}\n是否继续分析其他股票？(y/n): ").strip().lower()
            )
            if continue_choice not in ["y", "yes", "是", ""]:
                break

        except KeyboardInterrupt:
            print("\n👋 程序退出")
            break
        except Exception as e:
            logger.error("程序出错: %s", e)
            print(f"❌ 程序出错: {e}")
            continue

    print("\n🎉 分析完成！")


if __name__ == "__main__":
    main()
