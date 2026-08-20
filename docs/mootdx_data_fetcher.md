> ⛔ **v4 已弃用**：数据源已统一为 Tushare（私有代理 ts-2.cwy666.com），**mootdx 已弃用**，本文档仅作历史归档参考，不再维护。对应代码 `mootdx_data_fetcher.py` 保留在 `project_backup/` 冻结，不进入改造区。弃用原因：mootdx 0.11.7 对历史日期范围查询存在固有 bug，且行情服务器权限/连通性不稳定。详见《缠论项目工程优化-分步执行清单.md》Step 3-2。

# mootdx_data_fetcher.md - Mootdx数据获取器

## 📋 文件概述

`mootdx_data_fetcher.py` 是基于Mootdx库的股票数据获取工具，支持多市场数据获取（A股、ETF、港股、指数、北交所），包含通达信线路测试、最优线路存储和完整的数据清洗功能。

## 🎯 主要功能

### 核心特性
- **多市场支持**：A股、ETF、港股、指数、北交所
- **多服务器**：20个通达信服务器，自动选择最优线路
- **数据清洗**：自动处理异常值、缺失值
- **复权支持**：支持前复权、后复权、不复权
- **批量获取**：支持多只股票批量数据获取
- **上下文管理**：支持with语句自动连接/断开

## 🏗️ 类说明

### MootdxDataFetcher类

#### 类属性
```python
class MootdxDataFetcher:
    """基于mootdx的股票数据获取器"""
```

**主要属性**：
- `config_file`：最优线路配置文件路径（best_server.json）
- `optimal_server`：最优服务器（IP:Port）
- `optimal_latency`：最优服务器延迟（毫秒）
- `last_test_time`：最后测试时间
- `is_connected`：连接状态

#### 通达信服务器列表

```python
TDX_SERVERS = [
    ('114.80.63.12', 7709),
    ('60.12.136.250', 7709),
    # ... 共20个服务器
]
```

## 📖 方法详解

### 服务器管理方法

#### `_test_server_connection(self, host, port, timeout=3) -> Optional[float]`
测试单个服务器的连接延迟

```python
def _test_server_connection(
    self, 
    host: str, 
    port: int, 
    timeout: int = 3
) -> Optional[float]
```

**参数说明**：
- `host`：服务器IP
- `port`：服务器端口
- `timeout`：超时时间（秒）

**返回值**：
- 连接成功返回延迟（毫秒），失败返回None

#### `_test_all_servers(self) -> List[tuple]`
测试所有服务器线路

```python
def _test_all_servers(self) -> List[tuple]
```

**返回值**：
- 列表：[(server_str, latency_ms), ...]，按延迟排序

#### `_test_and_save_best_server(self) -> bool`
测试所有线路并保存最优线路

```python
def _test_and_save_best_server(self) -> bool
```

**返回值**：
- 成功返回True，否则返回False

#### `_load_optimal_server(self) -> bool`
从配置文件加载最优线路

```python
def _load_optimal_server(self) -> bool
```

**返回值**：
- 加载成功返回True，否则返回False

**验证规则**：
- 配置文件必须存在
- 必须包含optimal_server和last_updated字段
- 配置不超过7天
- 服务器仍然可用

#### `_save_optimal_server(self)`
保存最优线路到配置文件

```python
def _save_optimal_server(self)
```

**保存内容**：
```json
{
  "optimal_server": "114.80.63.12:7709",
  "latency_ms": 45.23,
  "last_updated": "2025-12-29T10:30:00"
}
```

### 数据获取方法

#### `get_daily_data(self, stock_code, start_date, end_date, frequency='d', adjustflag='2')`
获取日K线数据

```python
def get_daily_data(
    self, 
    stock_code: str, 
    start_date: str, 
    end_date: str,
    frequency: str = 'd',
    adjustflag: str = '2'
) -> pd.DataFrame
```

**参数说明**：
- `stock_code`：股票代码（sh.600000 / sz.000001）
- `start_date`：开始日期（YYYY-MM-DD）
- `end_date`：结束日期（YYYY-MM-DD）
- `frequency`：频率（'d'=日线，'w'=周线，'m'=月线）
- `adjustflag`：复权类型（'3'=不复权，'1'=后复权，'2'=前复权）

**返回值**：
- 清理后的DataFrame

**使用示例**：
```python
with MootdxDataFetcher() as fetcher:
    data = fetcher.get_daily_data(
        stock_code="sh.600000",
        start_date="2024-01-01",
        end_date="2024-12-31",
        adjustflag="2"
    )
```

#### `get_minute_data(self, stock_code, start_date, end_date, frequency='30', adjustflag='2')`
获取分钟K线数据

```python
def get_minute_data(
    self, 
    stock_code: str, 
    start_date: str, 
    end_date: str,
    frequency: str = '30',
    adjustflag: str = '2'
) -> pd.DataFrame
```

**参数说明**：
- `stock_code`：股票代码（sh.600000 / sz.000001）
- `start_date`：开始日期（YYYY-MM-DD）
- `end_date`：结束日期（YYYY-MM-DD）
- `frequency`：分钟频率（'5'/'15'/'30'/'60'）
- `adjustflag`：复权类型（'3'=不复权，'1'=后复权，'2'=前复权）

**返回值**：
- 清理后的DataFrame

**使用示例**：
```python
with MootdxDataFetcher() as fetcher:
    data = fetcher.get_minute_data(
        stock_code="sh.600000",
        start_date="2024-12-01",
        end_date="2024-12-31",
        frequency="30"
    )
```

#### `get_hk_stock_data(self, stock_code, start_date, end_date, data_type='daily', frequency='30')`
获取港股数据

```python
def get_hk_stock_data(
    self,
    stock_code: str,
    start_date: str,
    end_date: str,
    data_type: str = 'daily',
    frequency: str = '30'
) -> pd.DataFrame
```

**参数说明**：
- `stock_code`：港股代码（00700.HK 或 700）
- `start_date`：开始日期（YYYY-MM-DD）
- `end_date`：结束日期（YYYY-MM-DD）
- `data_type`：数据类型（'daily' 或 'minute'）
- `frequency`：分钟频率（仅当data_type='minute'时有效）

**返回值**：
- 清理后的DataFrame

**使用示例**：
```python
with MootdxDataFetcher() as fetcher:
    # 港股日线
    daily_data = fetcher.get_hk_stock_data(
        stock_code="00700",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_type='daily'
    )
    
    # 港股分钟线
    minute_data = fetcher.get_hk_stock_data(
        stock_code="00700",
        start_date="2024-12-01",
        end_date="2024-12-31",
        data_type='minute',
        frequency='30'
    )
```

#### `get_etf_data(self, etf_code, start_date, end_date, data_type='daily', frequency='30')`
获取ETF数据

```python
def get_etf_data(
    self,
    etf_code: str,
    start_date: str,
    end_date: str,
    data_type: str = 'daily',
    frequency: str = '30'
) -> pd.DataFrame
```

**参数说明**：
- `etf_code`：ETF代码（sh.510300 或 510300）
- `start_date`：开始日期（YYYY-MM-DD）
- `end_date`：结束日期（YYYY-MM-DD）
- `data_type`：数据类型（'daily' 或 'minute'）
- `frequency`：分钟频率

**返回值**：
- 清理后的DataFrame

**注意**：ETF不支持复权

**使用示例**：
```python
with MootdxDataFetcher() as fetcher:
    data = fetcher.get_etf_data(
        etf_code="588000",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_type='daily'
    )
```

#### `get_index_data(self, index_code, start_date, end_date, data_type='daily', frequency='30')`
获取指数数据

```python
def get_index_data(
    self,
    index_code: str,
    start_date: str,
    end_date: str,
    data_type: str = 'daily',
    frequency: str = '30'
) -> pd.DataFrame
```

**参数说明**：
- `index_code`：指数代码（sh.000001 或 000001）
- `start_date`：开始日期（YYYY-MM-DD）
- `end_date`：结束日期（YYYY-MM-DD）
- `data_type`：数据类型（'daily' 或 'minute'）
- `frequency`：分钟频率

**返回值**：
- 清理后的DataFrame

**使用示例**：
```python
with MootdxDataFetcher() as fetcher:
    data = fetcher.get_index_data(
        index_code="000001",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_type='daily'
    )
```

#### `get_realtime_quotes(self, stock_codes: List[str])`
获取实时行情报价

```python
def get_realtime_quotes(self, stock_codes: List[str]) -> pd.DataFrame
```

**参数说明**：
- `stock_codes`：股票代码列表（['600000', '000001']）

**返回值**：
- 实时行情DataFrame

**使用示例**：
```python
with MootdxDataFetcher() as fetcher:
    quotes = fetcher.get_realtime_quotes(["600000", "000001", "000300"])
    print(quotes)
```

### 辅助方法

#### `normalize_stock_code(self, code: str) -> str`
标准化股票代码

```python
def normalize_stock_code(self, code: str) -> str
```

**参数说明**：
- `code`：用户输入的股票代码

**返回值**：
- 标准化后的股票代码

#### `_get_market_from_code(self, stock_code: str) -> int`
从股票代码获取市场类型

```python
def _get_market_from_code(self, stock_code: str) -> int
```

**返回值**：
- 市场类型（1=上海, 0=深圳）

#### `_get_pure_code(self, stock_code: str) -> str`
获取纯数字股票代码

```python
def _get_pure_code(self, stock_code: str) -> str
```

**返回值**：
- 纯数字代码（如600000）

### 上下文管理器

#### `__enter__(self)`
上下文管理器入口

```python
def __enter__(self)
```
- 自动调用`login()`
- 返回self实例

#### `__exit__(self, exc_type, exc_val, exc_tb)`
上下文管理器出口

```python
def __exit__(self, exc_type, exc_val, exc_tb)
```
- 自动调用`logout()`
- 确保资源正确释放

## 💡 使用示例

### 基本使用

#### A股数据获取

```python
from mootdx_data_fetcher import MootdxDataFetcher

with MootdxDataFetcher() as fetcher:
    # 日线数据
    daily_data = fetcher.get_daily_data(
        stock_code="600000",
        start_date="2024-01-01",
        end_date="2024-12-31"
    )
    
    # 分钟数据
    minute_data = fetcher.get_minute_data(
        stock_code="000001",
        start_date="2024-12-01",
        end_date="2024-12-31",
        frequency="30"
    )
```

#### 港股数据获取

```python
with MootdxDataFetcher() as fetcher:
    # 日线数据
    daily_data = fetcher.get_hk_stock_data(
        stock_code="00700",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_type='daily'
    )
    
    # 分钟数据
    minute_data = fetcher.get_hk_stock_data(
        stock_code="00700",
        start_date="2024-12-01",
        end_date="2024-12-31",
        data_type='minute',
        frequency='30'
    )
```

#### ETF数据获取

```python
with MootdxDataFetcher() as fetcher:
    data = fetcher.get_etf_data(
        etf_code="588000",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_type='daily'
    )
```

#### 指数数据获取

```python
with MootdxDataFetcher() as fetcher:
    data = fetcher.get_index_data(
        index_code="000001",
        start_date="2024-01-01",
        end_date="2024-12-31",
        data_type='daily'
    )
```

### 高级使用

#### 测试港股数据

```python
with MootdxDataFetcher() as fetcher:
    fetcher.test_hk_daily_data()
```

#### 批量获取数据

```python
with MootdxDataFetcher() as fetcher:
    stocks = ["sh.600000", "sz.000001", "sh.600519"]
    
    # A股批量获取
    for stock in stocks:
        data = fetcher.get_daily_data(
            stock_code=stock,
            start_date="2024-01-01",
            end_date="2024-12-31"
        )
        print(f"{stock}: {len(data)} 行数据")
```

#### 手动服务器测试

```python
fetcher = MootdxDataFetcher()

# 测试所有服务器
results = fetcher._test_all_servers()

# 显示结果
for server, latency in results:
    print(f"{server}: {latency:.2f}ms")
```

## 📊 数据格式

### 输出DataFrame列说明

| 列名 | 类型 | 说明 |
|-----|------|------|
| datetime | datetime | 日期时间 |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| volume | float | 成交量 |
| amount | float | 成交额 |
| code | str | 股票代码 |

## ⚙️ 配置说明

### 服务器配置

**best_server.json文件**：
```json
{
  "optimal_server": "114.80.63.12:7709",
  "latency_ms": 45.23,
  "last_updated": "2025-12-29T10:30:00"
}
```

**配置更新**：
- 配置7天后自动过期
- 过期后自动重新测试
- 保存最优服务器

### 复权类型

| 类型 | 参数 | 说明 |
|-----|------|------|
| 不复权 | '3' | 原始价格，不复权处理 |
| 前复权 | '2' | 向前复权，适合长期分析 |
| 后复权 | '1' | 向后复权，适合短期分析 |

### K线频率

#### 日线频率
- 'd'：日线
- 'w'：周线
- 'm'：月线

#### 分钟频率
- '1'：1分钟（使用5分钟代替）
- '5'：5分钟
- '15'：15分钟
- '30'：30分钟
- '60'：60分钟

## ⚠️ 注意事项

1. **连接状态**：
   - 使用上下文管理器自动管理连接
   - 避免频繁连接/断开

2. **服务器选择**：
   - 自动选择延迟最低的服务器
   - 配置7天后自动过期
   - 可手动删除配置文件重新测试

3. **股票代码**：
   - A股需要交易所前缀（sh./sz.）
   - 港股支持多种格式（00700 / 00700.HK）
   - ETF和指数代码格式要正确

4. **日期格式**：
   - 必须使用YYYY-MM-DD格式
   - 结束日期不能早于开始日期

5. **分钟数据**：
   - 分钟数据获取较慢
   - 建议缩短时间范围
   - 部分分钟频率可能不支持

6. **数据清洗**：
   - 自动清洗会减少数据量
   - 查看清洗后的数据量
   - 如数据过少，检查清洗规则

## 🐛 常见问题

### Q1: 连接失败

**原因**：网络问题或所有服务器不可用

**解决方法**：
```python
# 检查网络连接
fetcher = MootdxDataFetcher()
results = fetcher._test_all_servers()
print(f"可用服务器: {len(results)} 个")
```

### Q2: 港股数据获取失败

**原因**：
- 股票代码格式错误
- 港股服务器不可用
- 网络连接问题

**解决方法**：
```python
# 测试港股服务器
fetcher = MootdxDataFetcher()
hk_data = fetcher.get_hk_stock_data(
    stock_code="00700",
    start_date="2024-01-01",
    end_date="2024-12-31",
    data_type='daily'
)
```

### Q3: 数据获取很慢

**原因**：
- 服务器延迟高
- 数据量大
- 分钟数据获取

**解决方法**：
- 删除best_server.json重新测试
- 缩短时间范围
- 使用日线数据

### Q4: 数据清洗后数据量过少

**原因**：数据质量差或异常值多

**解决方法**：
- 检查原始数据
- 调整清洗规则
- 选择其他股票

### Q5: ETF数据获取失败

**原因**：
- ETF代码格式错误
- ETF不支持该市场

**解决方法**：
```python
# 检查ETF代码
code = fetcher.normalize_stock_code("588000")
print(f"标准化代码: {code}")  # sh.588000
```

## 📚 相关文档

- [Mootdx Chanlun 主程序](mootdx_chanlun.md)
- [缠论核心算法](chanlun_processor.md)
- [项目主README](../README.md)
- [Mootdx官方文档](https://github.com/shidengdev/mootdx)
