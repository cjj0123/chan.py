# 自动下载自选股数据使用指南

## 功能说明

本脚本实现了以下功能：

1. **自动获取富途自选股列表** - 从富途OpenD获取用户的所有自选股
2. **多时间级别数据下载** - 支持日线、30分钟、5分钟、1分钟四个时间级别
3. **历史数据补齐** - 自动补齐2024年1月1日以来的完整历史数据
4. **增量更新** - 智能检测数据库中已有的数据，只下载缺失的数据
5. **多市场支持** - 同时支持A股、港股、美股
6. **自动调度** - 可配置crontab实现每日盘后自动下载

## 文件说明

- `auto_download_watchlist_data.py` - 主要的下载脚本
- `crontab_auto_download.txt` - crontab配置文件

## 使用方法

### 1. 补齐历史数据

```bash
# 补齐所有自选股自2024年1月1日以来的完整历史数据
python3 auto_download_watchlist_data.py
```

### 2. 下载今日数据

```bash
# 只下载今日的最新数据（用于每日盘后执行）
python3 auto_download_watchlist_data.py today
```

### 3. 设置自动调度

#### 安装crontab

1. 编辑crontab配置：
   ```bash
   crontab -e
   ```

2. 将 `crontab_auto_download.txt` 中的内容复制到crontab文件末尾

3. 保存并退出

#### crontab配置说明

- **A股/港股**：每天16:30（北京时间）执行，覆盖A股和港股收盘后的数据
- **美股**：每天9:30（北京时间，对应美股前一交易日收盘后）执行，覆盖美股数据

> 注意：根据您的实际需求，可以选择启用其中一个或两个都启用。

## 数据源策略

- **A股/港股**：优先使用Futu数据源，失败时回退到AKShare
- **美股**：使用AKShare数据源

## 增量更新机制

脚本会自动检测数据库中每个股票在每个时间级别的已有数据范围：
- 如果数据库中没有数据，下载完整的指定日期范围
- 如果数据库中有部分数据，只下载缺失的时间段
- 避免重复下载已有的数据，节省时间和API调用

## 错误处理

- 富途连接失败时，自动使用默认的测试股票列表
- 单个股票下载失败不会影响其他股票的下载
- 详细的日志输出，便于排查问题

## 验证数据

下载完成后，可以通过以下SQL查询验证数据：

```sql
-- 检查腾讯（HK.00700）的日线数据范围
SELECT code, MIN(date) as min_date, MAX(date) as max_date 
FROM kline_day 
WHERE code = 'HK.00700' 
GROUP BY code;

-- 检查30分钟线数据范围  
SELECT code, MIN(date) as min_date, MAX(date) as max_date 
FROM kline_30m 
WHERE code = 'HK.00700' 
GROUP BY code;
```

## 注意事项

1. **确保富途OpenD正在运行** - 脚本需要连接到富途OpenD获取自选股列表
2. **网络连接** - 需要稳定的网络连接来访问AKShare和Futu API
3. **磁盘空间** - 多时间级别数据会占用较多存储空间
4. **API限制** - 注意各数据源的API调用频率限制
5. **路径配置** - 确保crontab中的项目路径和Python路径正确