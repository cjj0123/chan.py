缠论量化机器人 (Chanlun Bot) 项目知识库

1. 核心架构设计 (Architectural Patterns)

多层过滤信号机制 (Multi-Layer Signal Filtering)
- 底层：严格的缠论几何划分（笔、线段、中枢）。
- 共振层：30M 定向 + 5M 定位。5M 信号必须在 30M 买点确认后的极短窗口内出现。
- AI 校验层：XGBoost/MLP 模型一票否决。引入 MAE (Maximum Adverse Excursion) 惩罚，过滤高波动易扫损标的。
- 视觉终审层：GPT-4V 对 30M+5M 组合图进行视觉评分。

异步并发扫描 (Async Parallel Scanning)
- 并发模型：asyncio 事件循环 + ThreadPoolExecutor。
- 性能优化：通过信号量（Semaphore）控制 API 频率，结合线程锁（Lock）保护非线程安全的券商 API 句柄。
- 提升效果：70 只股票扫描时间从 120s 降低至 30s 以内。

2. 交易与风险控制 (Trading & Risk Control)

动态仓位管理 (Dynamic Position Sizing)
- 凯利公式 (Kelly Criterion)：仓位 = f^* \times \text{基础占比}。f^* 由 ML 预测胜率 p 与盈亏比 b 动态计算。
- ATR 波动率对齐：止损位由 1.2 \times \text{ATR} 动态计算，而非固定百分比。

离场算法 (Exit Strategies)
- 分阶段移动止损：获利 > 1.5 \times \text{ATR} 后激活，回撤 > 2.5 \times \text{ATR} 平仓。
- 时间止损 (Time-Stop)：持仓 > 25 根 30M K线且未脱离成本区，主动释放资金。
- 快速回撤早走：盈利状态下回撤 > 1.0 \times \text{ATR} 提前锁定利润。

3. 机器学习优化 (ML Optimization)

滚动前向演练 (Walk-Forward Optimization)
- 逻辑：每月滚动更新训练集，模拟实盘定期微调。
- 特征工程：引入市场大环境特征（Market Regime），如所属大盘指数的动量（ROC）与波动率。

4. 故障演灾与后备链路

- API 冗余：Futu/IB 失效时回退至免费数据链（Akshare）。
- 价格复权校准：自动处理除权除息导致的 K 线断裂。

5. 自动化维护与数据流水线 (Maintenance & Data Pipeline)

串联级联自愈流 (Chained Auto-Sync Pipeline)
- **解决竞态**：传统定时任务由于先后独立（例如 06:00 增量 + 08:15 扫热点），容易导致新扫出的热点股在开盘前错失实时 K 线补齐。数据对不上。
- **级联驱动**：重构 `daily_incremental_sync.sh`，采用 `daily_hot_scanner.py` 执行完写完自选后，物理级联触发 `sync_all_history.py` 的架构，保障 100% 串流感知。

macOS 周期性调度托管 (launchd Ecosystem)
- **取代 Crontab**：在 `~/Library/LaunchAgents/` 中使用单发 `.plist` 配置文件（如 `incremental_sync` 托管）。
- **时间节拍**：设定在工作日（Mon-Fri）早晨 **08:30** 统合唤醒，彻底降噪多余的 standalone plist 重复负荷，保证盘前全向数据自愈闭环。

