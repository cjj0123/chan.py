# 数据库修复指南

本指南说明如何使用 `check_data_integrity.py` 和 `repair_data.py` 脚本来诊断和修复 `chan_trading.db` 数据库中的缺失数据。

## 1. 数据完整性诊断

使用 `check_data_integrity.py` 脚本检查特定股票在指定时间级别的数据完整性。

### 基本用法

```bash
# 检查单个股票的日线数据（默认日期范围：数据库最早日期到今天）
python check_data_integrity.py --code SH.600519 --timeframe day

# 检查指定日期范围的数据
python check_data_integrity.py --code SH.600519 --timeframe 30m --start 2024-01-01 --end 2024-12-31

# 指定数据库路径
python check_data_integrity.py --db /path/to/your/database.db --code SH.600519 --timeframe day
```

### 参数说明

- `--code`: 要检查的股票代码（必需）
- `--timeframe`: 时间级别，可选值：`day`, `30m`, `5m`, `1m`（默认：`day`）
- `--start`: 检查开始日期（格式：YYYY-MM-DD）
- `--end`: 检查结束日期（格式：YYYY-MM-DD，默认：今天）
- `--db`: 数据库文件路径（默认：`chan_trading.db`）

脚本会生成一个 JSON 文件（如 `diagnosis_SH.600519_day.json`），包含详细的诊断结果。

## 2. 数据修复

使用 `repair_data.py` 脚本修复缺失的数据。支持两种模式：

### 2.1 单股票修复模式

基于诊断结果 JSON 文件修复单个股票的数据。

```bash
# 使用诊断结果文件修复数据
python repair_data.py --diagnosis diagnosis_SH.600519_day.json
```

### 2.2 批量修复模式（推荐）

从富途自选股获取股票列表，对所有股票进行批量诊断和修复。

```bash
# 批量修复所有自选股（默认日期范围：2024-01-01 到今天）
python repair_data.py --batch

# 指定特定的时间级别
python repair_data.py --batch --timeframes day 30m

# 指定自定义日期范围
python repair_data.py --batch --start-date 2024-01-01 --end-date 2024-12-31

# 修复所有时间级别
python repair_data.py --batch --timeframes day 30m 5m 1m
```

### 批量修复参数说明

- `--batch`: 启用批量修复模式
- `--timeframes`: 要修复的时间级别列表（默认：`day 30m 5m 1m`）
- `--start-date`: 修复开始日期（默认：`2024-01-01`）
- `--end-date`: 修复结束日期（默认：今天）

## 3. 工作流程建议

1. **首次使用**：先运行批量修复模式，确保所有自选股的基础数据完整
   ```bash
   python repair_data.py --batch
   ```

2. **定期维护**：设置定时任务定期运行批量修复
   ```bash
   # 每天凌晨2点运行（添加到 crontab）
   0 2 * * * cd /path/to/Chanlun_Bot && python repair_data.py --batch
   ```

3. **问题排查**：如果发现特定股票有问题，可以单独诊断和修复
   ```bash
   python check_data_integrity.py --code SH.600519 --timeframe day --start 2024-01-01
   python repair_data.py --diagnosis diagnosis_SH.600519_day.json
   ```

4. **验证修复结果**：修复完成后，建议再次运行诊断脚本验证数据完整性

## 4. 注意事项

- **富途连接**：批量修复模式需要富途 OpenD 正常运行并已配置自选股分组
- **网络依赖**：修复过程需要网络连接来下载缺失的数据
- **API限制**：注意 Futu、AKShare 等数据源的 API 调用频率限制
- **数据库锁定**：修复过程中请勿同时运行其他写入数据库的程序
- **时间范围**：批量修复默认使用 2024-01-01 到今天的日期范围，可根据需要调整

## 5. 故障排除

### 富途连接失败
- 确保富途 OpenD 已启动
- 检查 `Config/config.yaml` 中的富途配置是否正确
- 确认自选股分组已创建

### 数据下载失败
- 检查网络连接
- 确认数据源（Futu/AKShare/BaoStock）可用
- 查看日志中的具体错误信息

### 数据库权限问题
- 确保脚本有读写 `chan_trading.db` 的权限
- 如果数据库被其他进程锁定，等待或重启相关进程

通过以上步骤，您可以有效地诊断和修复数据库中的缺失数据，确保缠论分析的准确性。