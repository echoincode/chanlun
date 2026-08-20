# enhanced_viz.py - Matplotlib可视化工具（v4）

## 📋 文件概述

`src/visual/enhanced_viz.py` 是基于Matplotlib的缠论K线可视化工具，提供鼠标悬停交互功能和完整的笔绘制功能，支持将图表导出为HTML文件。

> ⚠️ **v4 变更**：文件从根目录 `enhanced_visualizer.py` 迁移至 `src/visual/enhanced_viz.py`。
> 本模块为备选方案，主力可视化方案见 [plotly_visualizer.md](plotly_visualizer.md)。

## 🎯 主要功能

### 核心特性
- **K线绘制**：红涨绿跌的蜡烛图
- **成交量显示**：底部显示成交量柱状图
- **分型标记**：顶分型（红色倒三角）、底分型（绿色正三角）
- **笔绘制**：自动绘制上升笔（红色）和下降笔（绿色）
- **鼠标交互**：鼠标悬停显示详细信息
- **HTML导出**：支持导出为HTML文件（需要mpld3库）

## 🏗️ 类说明

### EnhancedChanlunVisualizer类

#### 类属性
```python
class EnhancedChanlunVisualizer:
    """增强版缠论可视化器"""
```

**主要属性**：
- `fig`：Matplotlib图形对象
- `ax`：主图坐标轴对象
- `ax_volume`：成交量图坐标轴对象
- `data`：当前显示的数据
- `cursor`：十字光标对象
- `annotation`：注解对象

## 📖 方法详解

### 主绘图方法

#### `plot_chanlun_with_interaction(self, data, start_idx=0, bars_to_show=100, data_type='daily', show_plot=True)`
绘制带交互功能的缠论K线图

```python
def plot_chanlun_with_interaction(
    self, 
    data, 
    start_idx=0, 
    bars_to_show=100, 
    data_type='daily', 
    show_plot=True
)
```

**参数说明**：
- `data`：包含缠论数据的DataFrame
- `start_idx`：起始索引
- `bars_to_show`：显示的K线数量
- `data_type`：K线类型（'daily' 或 'minute'）
- `show_plot`：是否显示图形

**数据要求**：
- 必需列：datetime, open, high, low, close
- 可选列：volume, fractal_type, is_fractal, segment_id

**功能流程**：
1. 数据验证（必需列检查、datetime类型转换）
2. 计算显示范围
3. 创建子图（K线图 + 成交量图）
4. 调用各绘图方法
5. 设置图表样式
6. 添加鼠标交互
7. 显示或保存图表

**使用示例**：
```python
from src.visual.enhanced_viz import EnhancedChanlunVisualizer

visualizer = EnhancedChanlunVisualizer()
visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily'
)
```

### K线绘制方法

#### `plot_candlesticks(self)`
绘制K线

```python
def plot_candlesticks(self)
```

**功能**：
- 绘制蜡烛图实体
- 绘制上下影线
- 根据涨跌设置颜色（红涨绿跌）

**颜色规则**：
- 上涨K线（close ≥ open）：红色
- 下跌K线（close < open）：绿色

**绘制细节**：
- 影线：黑色线条，线宽0.5，透明度0.7
- 实体：彩色矩形，线宽0.5，透明度0.8

### 成交量绘制方法

#### `plot_volume(self)`
绘制成交量

```python
def plot_volume(self)
```

**功能**：
- 绘制成交量柱状图
- 根据涨跌设置颜色（红涨绿跌）
- 设置X轴标签与K线图同步

**颜色规则**：
- 阳线K线：红色柱
- 阴线K线：绿色柱

### 分型标记方法

#### `mark_fractals(self)`
标记分型

```python
def mark_fractals(self)
```

**功能**：
- 识别数据中的分型
- 绘制分型标记符号

**标记样式**：
- 顶分型：红色倒三角（marker='v'），大小75
- 底分型：绿色正三角（marker='^'），大小75

### 笔绘制方法

#### `draw_segments(self)`
绘制笔

```python
def draw_segments(self)
```

**功能**：
- 识别数据中的笔
- 绘制笔连线

**绘制规则**：
- 上升笔：红色线条，线宽2.5，透明度0.8
- 下降笔：绿色线条，线宽2.5，透明度0.8

**绘制逻辑**：
1. 找到所有笔的端点
2. 根据笔的类型（顶→底或底→顶）确定起点和终点
3. 计算方向并选择颜色
4. 绘制连线

### 辅助方法

#### `find_opposite_fractal(self, start_point)`
查找相反的分型作为笔的终点

```python
def find_opposite_fractal(self, start_point)
```

**参数说明**：
- `start_point`：笔的起点（分型）

**返回值**：
- 相反类型的分型（如果找到）

### 样式设置方法

#### `setup_chart_style(self, end_idx)`
设置图表样式

```python
def setup_chart_style(self, end_idx)
```

**功能**：
- 设置图表标题
- 设置坐标轴标签
- 添加网格线
- 设置Y轴格式
- 添加图例
- 添加信息框

**信息框内容**：
- 价格区间（最低价 - 最高价）
- K线数量
- 时间范围（开始日期 - 结束日期）

### 交互方法

#### `setup_mouse_interaction(self)`
设置鼠标交互功能

```python
def setup_mouse_interaction(self)
```

**功能**：
- 创建十字光标
- 添加鼠标移动事件
- 创建注解对象

**交互效果**：
- 十字光标：红色线条
- 注解框：黄色背景，圆角样式

#### `on_mouse_move(self, event)`
鼠标移动事件处理

```python
def on_mouse_move(self, event)
```

**功能**：
- 捕获鼠标位置
- 找到最近的K线
- 显示K线详细信息

**显示信息**：
- 时间
- 开盘价、最高价、最低价、收盘价
- 涨跌额和涨跌幅
- 分型类型（如果是分型）
- 成交量（如果有）
- 笔ID（如果是笔端点）

## 💡 使用示例

### 基本使用

```python
from src.visual.enhanced_viz import EnhancedChanlunVisualizer

# 创建可视化器
visualizer = EnhancedChanlunVisualizer()

# 绘制图表
visualizer.plot_chanlun_with_interaction(
    data=result,           # 缠论分析结果
    start_idx=0,           # 从第0根开始
    bars_to_show=100,      # 显示100根K线
    data_type='daily',     # 日线数据
    show_plot=True         # 显示图表
)
```

### 调整显示范围

```python
# 显示第50-150根K线
visualizer.plot_chanlun_with_interaction(
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
from src.visual.enhanced_viz import enhanced_chanlun_visualization

# 导出为HTML文件
success = enhanced_chanlun_visualization(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    save_html='output.html'  # 指定HTML文件路径
)

if success:
    print("HTML文件导出成功")
else:
    print("HTML文件导出失败")
```

### 仅导出不显示

```python
# 不显示图表，只保存HTML
visualizer = EnhancedChanlunVisualizer()
visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=100,
    data_type='daily',
    show_plot=False  # 不显示图表
)

# 手动保存HTML
import mpld3
html_str = mpld3.fig_to_html(visualizer.fig)
with open('output.html', 'w', encoding='utf-8') as f:
    f.write(html_str)
```

## 🎨 样式定制

### 修改颜色

```python
visualizer = EnhancedChanlunVisualizer()

# 修改K线颜色
visualizer.plot_candlesticks = lambda: [
    # 自定义颜色逻辑
    # 例如：上涨用绿色，下跌用红色
]

# 修改分型标记颜色
visualizer.mark_fractals = lambda: [
    # 自定义分型颜色
]

# 修改笔颜色
visualizer.draw_segments = lambda: [
    # 自定义笔颜色
]
```

### 修改图表布局

```python
import matplotlib.pyplot as plt

# 创建自定义布局
visualizer.fig, (visualizer.ax, visualizer.ax_volume) = plt.subplots(
    2, 1, 
    figsize=(20, 12),         # 更大的图表
    gridspec_kw={'height_ratios': [4, 1]}  # K线图占4倍，成交量图占1倍
)
```

### 修改信息框内容

```python
visualizer.setup_chart_style = lambda end_idx: [
    # 自定义信息框内容
    info_text = (
        f"股票代码: {stock_code}\n"
        f"当前价格: {current_price:.2f}\n"
        f"涨跌幅: {change_pct:+.2f}%\n"
        # 添加更多信息...
    )
    
    visualizer.ax.text(
        0.02, 0.98, 
        info_text, 
        transform=visualizer.ax.transAxes,
        fontsize=12, 
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    )
]
```

## 📊 图表元素说明

### K线图元素

| 元素 | 描述 | 颜色 |
|-----|------|------|
| 蜡烛实体 | 开盘价和收盘价之间的矩形 | 红色（涨）/绿色（跌）|
| 上下影线 | 最高价和最低价之间的线条 | 黑色 |
| 顶分型标记 | 倒三角形 | 红色 |
| 底分型标记 | 正三角形 | 绿色 |
| 上升笔 | 从底到顶的连线 | 红色 |
| 下降笔 | 从顶到底的连线 | 绿色 |

### 成交量图元素

| 元素 | 描述 | 颜色 |
|-----|------|------|
| 成交量柱 | 对应K线的成交量 | 红色（阳线）/绿色（阴线）|

### 信息框内容

- 价格区间：最低价 - 最高价
- K线数量：显示的K线根数
- 时间范围：开始日期 - 结束日期

## ⚙️ 配置选项

### 中文字体设置

```python
try:
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
except:
    pass
```

**支持的字体**：
- SimHei（黑体）
- Microsoft YaHei（微软雅黑）
- Arial Unicode MS（Arial Unicode）

### 图表大小

```python
# 默认大小
figsize=(16, 10)

# 自定义大小
figsize=(20, 12)  # 更大的图表
figsize=(12, 8)   # 更小的图表
```

### 坐标轴比例

```python
# 默认比例
gridspec_kw={'height_ratios': [3, 1]}  # K线图:成交量图 = 3:1

# 自定义比例
gridspec_kw={'height_ratios': [4, 1]}  # K线图占更大比例
gridspec_kw={'height_ratios': [2, 1]}  # 成交量图占更大比例
```

## 🔍 交互功能

### 鼠标悬停信息

悬停在K线上时显示：
- 时间：日期时间
- 开盘价
- 最高价
- 最低价
- 收盘价
- 涨跌额
- 涨跌幅

### 分型信息

如果是分型，额外显示：
- 分型类型（顶分型/底分型）

### 笔信息

如果是笔端点，额外显示：
- 笔ID

### 成交量信息

如果有成交量数据，额外显示：
- 成交量

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

4. **HTML导出**：
   - 需要安装mpld3库
   - 安装命令：`pip install mpld3`
   - HTML文件包含交互功能

5. **性能考虑**：
   - 显示过多K线会影响性能
   - 建议每次显示100-200根K线
   - 大数据量考虑分批显示

6. **字体问题**：
   - Windows系统自带支持的中文字体
   - Linux/Mac可能需要安装中文字体
   - 字体不支持时显示方框

## 🐛 常见问题

### Q1: 中文显示为方框

**原因**：系统缺少中文字体

**解决方法**：
```python
# 方法1：使用系统字体
plt.rcParams['font.sans-serif'] = ['SimHei']

# 方法2：指定字体路径
import matplotlib.font_manager as fm
font_path = 'C:/Windows/Fonts/simhei.ttf'
prop = fm.FontProperties(fname=font_path)
plt.rcParams['font.family'] = prop.get_name()
```

### Q2: 图表显示不全

**原因**：显示范围超出数据

**解决方法**：
```python
# 调整显示范围
visualizer.plot_chanlun_with_interaction(
    data=result,
    start_idx=0,
    bars_to_show=min(100, len(result))  # 不超过数据长度
)
```

### Q3: HTML导出失败

**原因**：未安装mpld3库

**解决方法**：
```bash
pip install mpld3
```

### Q4: 笔没有绘制

**原因**：数据中缺少segment_id列

**解决方法**：
```python
# 确保数据包含segment相关列
required_columns = ['datetime', 'open', 'high', 'low', 'close', 
                   'fractal_type', 'is_fractal', 'segment_id']
```

### Q5: 分型没有标记

**原因**：数据中缺少fractal相关列

**解决方法**：
```python
# 确保数据包含fractal相关列
required_columns = ['datetime', 'open', 'high', 'low', 'close',
                   'fractal_type', 'is_fractal']
```

## 📚 相关文档

- [Plotly可视化工具](plotly_visualizer.md)
- [缠论核心算法](chanlun_processor.md)
- [BaoStock分析主程序](baostock_chanlun.md) ⛔ v4 已弃用（baostock 数据源弃用）
- [Matplotlib官方文档](https://matplotlib.org/)
- [mpld3文档](https://github.com/mpld3/mpld3)
