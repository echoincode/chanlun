# 可视化工具文档

本目录包含两个可视化工具的详细文档：

> ⚠️ **v4 改造说明**：可视化模块已迁移至 `src/visual/` 目录。
> - `plotly_visualizer.py` → `src/visual/plotly_viz.py`
> - `enhanced_visualizer.py` → `src/visual/enhanced_viz.py`

## 📚 文档列表

1. [enhanced_visualizer.md](enhanced_visualizer.md) - Matplotlib可视化工具
   - 鼠标悬停交互
   - 完整的笔绘制功能
   - 支持导出HTML文件

2. [plotly_visualizer.md](plotly_visualizer.md) - Plotly可视化工具
   - 丰富的交互功能（拖拽缩放、hover信息、Y轴调节）
   - 现代化的界面设计
   - 支持生成独立的HTML文件
   - **v4.1 笔连续折线修复**

## 🎯 工具对比

| 特性 | Matplotlib版 | Plotly版 |
|-----|------------|----------|
| 交互性 | 鼠标悬停 | 拖拽缩放 + hover + Y轴调节 |
| 性能 | 较好（适合大数据） | 优秀（现代浏览器优化） |
| 导出 | 需要mpld3库 | 原生支持HTML |
| 界面 | 经典风格 | 现代风格 |
| 浏览器兼容 | 良好 | 优秀 |
| 学习曲线 | 简单 | 中等 |
| 推荐场景 | 快速查看 | 深度分析 |

## 💡 选择建议

- **推荐使用 Plotly 版**：交互性更强，界面更现代，适合深度分析
- Matplotlib 版适合快速查看或无浏览器环境

## 🔧 v4 变更

### 文件位置
```
src/visual/plotly_viz.py      # Plotly 可视化（主力）
src/visual/enhanced_viz.py    # Matplotlib 可视化（备选）
```

### 笔绘制修复（v4.1）
原实现为每个笔单独创建独立线段（N 笔 = N 条互不相连的线），导致视觉上"笔在乱画、不连续"。

修复方案：将所有笔端点按时间顺序收集，连成一条连续折线（1 条 trace 包含全部端点），确保笔 0 终点 → 笔 1 起点 紧密相连。

### 使用示例
```python
from src.visual.plotly_viz import plotly_chanlun_visualization

# result 是 analyze() 返回的 DataFrame
fig = plotly_chanlun_visualization(
    result, start_idx=0, bars_to_show=len(result),
    data_type="daily", return_fig=True, stock_code="600519.SH"
)
fig.show()  # 在浏览器中打开
# 或保存为 HTML
fig.write_html("result.html")
```
