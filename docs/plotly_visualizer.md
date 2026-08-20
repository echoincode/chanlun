# plotly_viz.py - Plotly可视化工具（v4）

## 📋 文件概述

`src/visual/plotly_viz.py` 是基于Plotly的缠论K线可视化工具，支持丰富的交互功能，包括拖拽缩放、hover信息、Y轴调节等现代化特性，可直接生成独立的HTML文件。

> ⚠️ **v4 变更**：文件从根目录 `plotly_visualizer.py` 迁移至 `src/visual/plotly_viz.py`。
> **v4.1 修复**：笔绘制从独立线段改为连续折线，解决"笔在乱画、不连续"的问题。

## 🎯 主要功能

### 核心特性
- **K线绘制**：红涨绿跌的蜡烛图
- **成交量显示**：底部显示成交量柱状图
- **分型标记**：顶分型（红色倒三角）、底分型（绿色正三角）
- **笔绘制（v4.1 修复）**：所有笔端点连成**一条连续折线**，顶红点绿，确保笔与笔紧密相连
- **丰富交互**：拖拽缩放、pan、hover信息、Y轴调节
- **HTML导出**：原生支持HTML导出，无需额外库

## 🏗️ 类说明

### PlotlyChanlunVisualizer类

#### 类属性
```python
class PlotlyChanlunVisualizer:
    """基于Plotly的缠论可视化器"""
```

**主要属性**：
- `data`：当前显示的数据
- `fig`：Plotly Figure对象

## 📖 方法详解

### 主绘图方法

#### `plot_chanlun_with_interaction(self, data, start_idx=0, bars_to_show=100, data_type='daily', show_plot=True)`
绘制带丰富交互功能的缠论K线图

```python
def plot_chanlun_with_interaction(
    self, 
    data, 
    start_idx=0, 
    bars_to_show=100, 
    data_type='daily', 
    show_plot=True
) -> go.Figure
```

**参数说明**：
- `data`：包含缠论数据的DataFrame
- `start_idx`：起始索引
- `bars_to_show`：显示的K线数量
- `data_type`：K线类型（'daily' 或 'minute'）
- `show_plot`：是否显示图形

**返回值**：
- Plotly Figure对象

**数据要求**：
- 必需列：datetime, open, high, low, close
- 可选列：volume, fractal_type, is_fractal, segment_id

**功能流程**：
1. 数据验证和转换
2. 计算Y轴范围
3. 配置X轴（日期轴或数值轴）
4. 创建子图（K线图 + 成交量图）
5. 绘制K线蜡烛图
6. 添加分型标记
7. 绘制笔
8. 添加成交量
9. 更新布局（标题、按钮、边距等）
10. 添加缩放和重置按钮

**使用示例**：
```python
from src.visual.plotly_viz import plotly_chanlun_visualization

fig = plotly_chanlun_visualization(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    return_fig=True,
    stock_code='600519.SH'
)
```

### 辅助方法

#### `_is_trading_time(self, dt)`
判断是否为交易时间

```python
def _is_trading_time(self, dt) -> bool
```

**参数说明**：
- `dt`：日期时间对象

**返回值**：
- 是否为交易时间（True/False）

**交易时间**：
- A股交易时间：
  - 上午：9:30-11:30
  - 下午：13:00-15:00

#### `_add_fractals(self, plot_data, data_type='daily')`
添加分型标记

```python
def _add_fractals(self, plot_data, data_type='daily')
```

**参数说明**：
- `plot_data`：要标记的数据
- `data_type`：数据类型（'daily' 或 'minute'）

**功能**：
- 识别数据中的分型
- 绘制分型标记符号

**标记样式**：
- 顶分型：红色倒三角（symbol='triangle-down'），大小6
- 底分型：绿色正三角（symbol='triangle-up'），大小6

#### `_draw_segments(self, plot_data, data_type='daily')`
绘制笔（v4.1 连续折线版）

```python
def _draw_segments(self, plot_data, data_type='daily')
```

**参数说明**：
- `plot_data`：要绘制笔的数据
- `data_type`：数据类型（'daily' 或 'minute'）

**功能**：
- 识别数据中的笔端点
- 将所有笔端点按时间顺序收集，连成**一条连续折线**

**绘制规则（v4.1 修复）**：
- 所有笔端点收集到 `all_x`/`all_y` 数组
- 一条 `go.Scatter` trace 包含全部端点（而非每笔独立线段）
- 确保笔 0 终点 → 笔 1 起点 紧密相连
- 端点颜色：顶分型红点 `#e74c3c`、底分型绿点 `#27ae60`
- 线条颜色：深灰 `#333333`，线宽 2.5

#### `_find_opposite_fractal(self, start_point, plot_data)`
查找相反的分型作为笔的终点

```python
def _find_opposite_fractal(self, start_point, plot_data)
```

**参数说明**：
- `start_point`：笔的起点（分型）
- `plot_data`：数据

**返回值**：
- 相反类型的分型（如果找到）

### 显示方法

#### `show(self)`
显示图表

```python
def show(self)
```

**功能**：
- 调用Plotly的show()方法
- 在浏览器中打开交互式图表

## 💡 使用示例

### 基本使用

```python
from src.visual.plotly_viz import plotly_chanlun_visualization

# 创建图表并显示
fig = plotly_chanlun_visualization(
    data=result,           # 缠论分析结果
    start_idx=0,           # 从第0根开始
    bars_to_show=100,      # 显示100根K线
    data_type='daily',     # 日线数据
    return_fig=False,      # 直接显示（默认）
    stock_code='600519.SH' # 股票代码（显示在标题中）
)
```

### 调整显示范围

```python
# 显示第50-150根K线
plotly_chanlun_visualization(
    data=result,
    start_idx=50,
    bars_to_show=100,
    data_type='daily'
)
```

### 显示分钟K线

```python
# 显示30分钟K线
visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=200,      # 分钟数据可以显示更多
    data_type='minute_30'  # 指明是30分钟线
)
```

### 导出HTML文件

```python
from src.visual.plotly_viz import plotly_chanlun_visualization

# 创建图表并导出HTML
fig = plotly_chanlun_visualization(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    return_fig=True,  # 返回Figure对象
    stock_code='600519.SH'
)

# 导出HTML
fig.write_html('output.html', include_plotlyjs='cdn')
print("HTML文件导出成功")
```

### 不显示图表，仅返回Figure对象

```python
# 不显示图表，只返回Figure对象
fig = plotly_chanlun_visualization(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    return_fig=True
)

# 后续可以自定义处理
fig.update_layout(
    title='自定义标题',
    height=800,
    showlegend=False
)

# 显示或保存
fig.show()
# 或
fig.write_html('custom.html')
```

### 自定义布局

```python
fig = visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    show_plot=False  # 不显示
)

# 自定义布局
fig.update_layout(
    title=dict(
        text='自定义标题',
        x=0.5,
        font=dict(size=20, color='blue')
    ),
    height=800,  # 自定义高度
    width=1200,  # 自定义宽度
    paper_bgcolor='white',  # 背景色
    plot_bgcolor='white',   # 绘图区背景色
    margin=dict(l=50, r=50, t=80, b=50),  # 边距
    font=dict(size=14)  # 全局字体大小
)

# 显示
fig.show()
```

## 🎨 样式定制

### 修改K线颜色

```python
fig = visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    show_plot=False
)

# 修改K线颜色（重新创建candlestick trace）
fig.data[0].update(
    increasing_line_color='red',      # 上涨K线颜色
    decreasing_line_color='green',     # 下跌K线颜色
    increasing_fillcolor='rgba(255,0,0,0.7)',  # 上涨K线填充
    decreasing_fillcolor='rgba(0,255,0,0.7)'   # 下跌K线填充
)

fig.show()
```

### 修改分型标记大小

```python
# 在_add_fractals方法中修改
marker=dict(
    symbol='triangle-down',
    size=10,  # 增大标记（默认6）
    color='red'
)
```

### 修改笔线宽

```python
# 在_draw_segments方法中修改
line=dict(
    color=color,
    width=3.5  # 增大线宽（默认2.5）
)
```

### 自定义Y轴范围

```python
fig = visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    show_plot=False
)

# 自定义Y轴范围
fig.update_yaxes(
    range=[yaxis_min, yaxis_max],  # 自定义范围
    autorange=False  # 禁用自动范围
)

fig.show()
```

### 自定义按钮

```python
fig = visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    show_plot=False
)

# 添加自定义按钮
fig.update_layout(
    updatemenus=[
        dict(
            type="buttons",
            direction="left",
            buttons=list([
                dict(
                    args=[{"yaxis.range": [yaxis_min, yaxis_max]}],
                    label="重置Y轴",
                    method="relayout"
                ),
                dict(
                    args=[{"yaxis.autorange": True}],
                    label="自动Y轴",
                    method="relayout"
                ),
                dict(
                    args=[{"xaxis.showgrid": True}],
                    label="显示网格",
                    method="relayout"
                ),
                dict(
                    args=[{"xaxis.showgrid": False}],
                    label="隐藏网格",
                    method="relayout"
                )
            ]),
            pad={"r": 10, "t": 10},
            showactive=True,
            x=0.01,
            xanchor="left",
            y=1.02,
            yanchor="top"
        ),
    ]
)

fig.show()
```

## 📊 图表元素说明

### K线图元素

| 元素 | 描述 | 颜色 |
|-----|------|------|
| 蜡烛实体 | 开盘价和收盘价之间的矩形 | 红色（涨）/绿色（跌）|
| 顶分型标记 | 倒三角形 | 红色 |
| 底分型标记 | 正三角形 | 绿色 |
| 笔（v4.1） | 所有笔端点连成一条连续折线 | 深灰（线条）+ 红/绿（端点）|

### 成交量图元素

| 元素 | 描述 | 颜色 |
|-----|------|------|
| 成交量柱 | 对应K线的成交量 | 红色（阳线）/绿色（阴线）|

### 控制按钮

| 按钮 | 功能 |
|-----|------|
| 重置Y轴 | 恢复默认Y轴范围 |
| 自动Y轴 | 启用自动Y轴调整 |

## ⚙️ 配置选项

### 图表大小

```python
# 默认大小
height=900

# 自定义高度
fig.update_layout(height=1200)  # 更高的图表
fig.update_layout(width=1000)    # 自定义宽度
```

### 子图比例

```python
# 默认比例
row_heights=[0.9, 0.1]  # K线图90%，成交量图10%

# 自定义比例
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.02,
    subplot_titles=('K线图', '成交量'),
    row_heights=[0.85, 0.15]  # K线图85%，成交量图15%
)
```

### X轴配置

#### 日线X轴

```python
xaxis_config = dict(
    title='日期',
    type='date',
    showgrid=True,
    gridwidth=1,
    gridcolor='lightgray'
)
```

#### 分钟线X轴

```python
xaxis_config = dict(
    title=f'K线序号 ({freq}分钟)',
    type='linear',
    showgrid=True,
    gridwidth=1,
    gridcolor='lightgray',
    tickmode='array',
    tickvals=tick_positions,
    ticktext=tick_labels
)
```

### Y轴配置

```python
fig.update_layout(
    yaxis=dict(
        title='价格',
        showgrid=True,
        gridwidth=1,
        gridcolor='lightgray',
        zeroline=False,
        range=[yaxis_min, yaxis_max],  # 使用计算的范围
        autorange=False  # 禁用自动范围，使用手动设置
    )
)
```

## 🔍 交互功能

### 拖拽缩放
- **功能**：按住鼠标拖拽可以缩放图表
- **激活方式**：设置`dragmode='zoom'`

### Pan平移
- **功能**：按住鼠标拖拽可以平移图表
- **激活方式**：设置`dragmode='pan'`

### Hover信息
- **K线Hover**：
  - 时间
  - 开盘价、最高价、最低价、收盘价
- **分型Hover**：
  - 时间
  - 类型（顶分型/底分型）
  - 价格
- **笔Hover**：
  - 起点和终点的分型信息

### Y轴调节
- **重置Y轴**：恢复默认Y轴范围
- **自动Y轴**：启用自动Y轴调整

### 交易时间高亮
- **功能**：自动识别A股交易时间并高亮
- **时间范围**：9:30-11:30、13:00-15:00

## 🌐 HTML导出

### 基本导出

```python
fig.write_html('output.html', include_plotlyjs='cdn')
```

**参数说明**：
- `file`：文件名
- `include_plotlyjs`：Plotly.js包含方式
  - `'cdn'`：从CDN加载（推荐）
  - `True`：嵌入到HTML文件（文件较大）
  - `False`：不包含（需要手动加载Plotly.js）

### 高级导出选项

```python
fig.write_html(
    'output.html',
    include_plotlyjs='cdn',
    config={'displayModeBar': True, 'responsive': True},
    full_html=False
)
```

**配置选项**：
- `displayModeBar`：显示工具栏
- `responsive`：响应式布局
- `full_html`：完整HTML文档（False则只包含图表部分）

## ⚠️ 注意事项

1. **数据格式**：
   - datetime列必须是datetime类型
   - 数据必须按时间排序

2. **数据列**：
   - 必需：datetime, open, high, low, close
   - 可选：volume, fractal_type, is_fractal, segment_id

3. **显示范围**：
   - start_idx + bars_to_show不能超过数据长度
   - 超出会自动截断

4. **浏览器要求**：
   - 需要现代浏览器（Chrome、Firefox、Edge、Safari）
   - 需要JavaScript支持

5. **网络要求**：
   - CDN模式需要网络连接
   - 嵌入模式不需要网络

6. **性能考虑**：
   - 显示过多K线会影响性能
   - 建议每次显示100-500根K线
   - Plotly优化较好，但仍有上限

7. **分钟K线特殊处理**：
   - 使用数值轴而不是日期轴
   - 自定义时间标签显示
   - 适合短期分析

## 🐛 常见问题

### Q1: 图表不显示

**原因**：浏览器不支持或JavaScript被禁用

**解决方法**：
- 使用现代浏览器
- 启用JavaScript
- 检查控制台错误信息

### Q2: 分型标记显示位置不对

**原因**：分钟K线使用数值轴导致坐标错误

**解决方法**：
```python
# 确保使用正确的x坐标
if data_type.startswith('minute_'):
    x_pos = idx - plot_data.index[0]  # 转换为相对位置
else:
    x_pos = fractal['datetime']  # 使用datetime
```

### Q3: HTML文件很大

**原因**：Plotly.js嵌入到HTML中

**解决方法**：
```python
# 使用CDN模式
fig.write_html('output.html', include_plotlyjs='cdn')
```

### Q4: CDN模式无法离线查看

**原因**：需要网络连接加载Plotly.js

**解决方法**：
```python
# 嵌入模式
fig.write_html('output.html', include_plotlyjs=True)
```

### Q5: 笔没有绘制

**原因**：数据中缺少segment_id列

**解决方法**：
```python
# 确保数据包含segment相关列
required_columns = ['datetime', 'open', 'high', 'low', 'close',
                   'fractal_type', 'is_fractal', 'segment_id']
```

### Q6: 成交量柱颜色不对

**原因**：涨跌颜色判断错误

**解决方法**：
```python
# 检查涨跌判断
colors = ['red' if close >= open else 'green'
         for close, open in zip(plot_data['close'], plot_data['open'])]
```

## 📚 相关文档

- [Enhanced Visualizer（Matplotlib版）](enhanced_visualizer.md)
- [缠论核心算法](chanlun_processor.md)
- [Plotly官方文档](https://plotly.com/python/)
- [Plotly Candlestick Charts](https://plotly.com/python/candlestick-charts/)
