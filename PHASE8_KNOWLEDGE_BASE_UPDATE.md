# 缠论量化机器人 (Chanlun Bot) 知识库 - Phase 8 调优更新

日期: 2026-03-24

---

## 🇺🇸 1. 美股 (IB/Schwab) 自动化交易链路稳固化

针对美股交易（Interactive Brokers 渠道）在无实时数据订阅、容易产生连接挂起等复杂环境下的深度调优，现已完成全链路闭环：

### 🔄 1.1 双源数据对齐策略 (The Dual-Source Strategy)
*   **痛点**：IB 官方 API 数据权限受限，无订阅时无法在 30M 级别进行缠论结构计算。
*   **方案**：建立 **"Schwab 分析 -> IB 执行"** 的解耦架构。
    *   **分析端**：系统在扫描前，自动从 **Charles Schwab API** 强力补齐最近 **15 天** 的 K 线数据至本地 SQLite 数据库。
    *   **执行端**：信号生成后，即便 IB 仅有延迟行情，系统仍能根据本地 DB 的缠论结构精准触发 IB 订单。
*   **同步深度**：默认同步窗口由 5 天延展至 **15 天**，完美覆盖节假日及无操作空窗期，确保缠论线段构造的持续性。

### 🛡️ 1.2 IB 异步主循环挂起修复 (Anti-Hang Architecture)
*   **变更**：彻底移除了易造成 `ib_insync` 协程阻塞的 `reqAccountUpdates()`。
*   **限锁**：为 IB 账户资产查询（`accountValues`）增加了 **5 次重试保护与超时退出机制**，防止在网络波动或网关超时时导致整个交易中枢“假死”。
*   **冷启动补偿**：扫描引擎增加了 **8 分钟窗口补偿逻辑**。启动程序后，若处于当前 30M 周期前 8 分钟内，将无视历史扫描状态立即补扫一次，缩短系统热机时间。

---

## ⏰ 2. macOS 周期性自动化维护 (launchd Ecosystem - V2)

自动化家政系统新增“守门员”任务，形成了 **[找股 - 存数 - 守门]** 的三位一体闭环：

### 🕒 C. IB 网关全自动看门狗 (`ib_watchdog`)
*   **配置文件**：`com.chanlun.ib_watchdog.plist`
*   **运行机制**：**Keep-Alive (常驻运行)**。
*   **入口命令**：`python3 scripts/ib_watchdog.py`
*   **核心逻辑**：
    1. 每 30 秒轮询本地 `4002` 端口。
    2. 若端口失效，通过 `IBC` 调用 `/Users/jijunchen/IBC/mac_gateway_start.sh` 自动重拉网关。
    3. 自动处理 Snowball Securities (Simulated Trading) 的登录与确认弹窗。
*   **作用**：彻底免除人工维护 IB Gateway 的负担，确保交易系统永远有可用的下单通道。

---

## 🎨 3. 生产环境日志降噪 (Production Optimization)
*   **清理**：移除了开发调试阶段的高频心跳探测日志 (Ping) 与冗余 `DEBUG:` 打印。
*   **规范**：日志窗口仅保留**关键业务状态**（连接成功、数据对账开始、信号触发预测结果、下单回执），大幅提升盘中盯盘的可读性。

---

## 🏆 4. 港股实盘最优策略变更 (基于 2026.03 回测)
*(略去此前 Phase 8 的重复细节，仍保持 30M 单周期无止损网格模型)*

---

*(注：以上变更已物理对齐至 `BaseUSTradingController.py`、`IBTradingController.py` 及 `SQLiteAPI.py`，全向自动化后台已上线稳定运行)*

---

## 🛠️ 4. 盘中避雷与效率优化 (已上线运行)

### 🏎️ 4.1 剥离常驻 API 心跳拉取 (持仓配额保护)
* **变更**：
  1. 在 `analyze_with_chan` 的 5M 逃顶探测中，用 `code in self.position_trackers` 内存缓存检查，代替实时 `get_position_quantity` API 调用。
  2. 在 `_check_trailing_stops`（移动止损轮询）中剥离了每步的持仓查询。仅在价格确实触发平仓并准备调用 `execute_trade` 前一毫微，现场拉取持仓校准。
* **作用**：掐死非必要的 Futu 查询流，彻底解决了高并发状态下的 Futu API 频控死锁与 100% 扫票卡慢瓶颈。

### 🚀 4.2 紧急离场市价单升级“5% 穿透限价单”
* **变更**：将紧急逃顶下的 `OrderType.MARKET` (市价单) 替换为带 **5% 价格缓冲区的 `OrderType.NORMAL` (增强限价单)**。
* **作用**：绕过特定通道（或暗盘、盘前盘后）对市价单的直接风控限售，保证穿透买卖盘的同时阻断暗盘闪崩拒单。

---

## 📝 5. 待实施优化清单 (Future Backlog)

### 🧠 5.1 机器学习推理加速 (ONNX Runtime 整合)
* **背景**：当前系统在 `analyze_with_chan` 中会频繁调用 `self.signal_validator.validate_signal` 进行 ML 概率预测。如果本地机器没有高性能 GPU，在大批并发（如遍历数百只股票）时，CPU 推理会导致线程阻塞或延迟，增加信号错过的风险。
* **规划**：
  * **技术方案**：将现有的 PyTorch/TensorFlow 预训练模型转换为 **ONNX 格式**，并在 `SignalValidator` 内部使用 `onnxruntime` 进行加载与推理。
  * **预期收益**：借助 C++ 绑定的轻量级推演引擎，CPU 推理效率可提升 **6至10 倍**，彻底消除 AI 推理引起的扫描队列拥堵，为标的池的大规模扩容（如全A股）奠定性能基础。

---
*(注：以上变动已物理对齐到 `config.py` 及 `HKTradingController.py` 主体，全向自动化后台无感静默部署)*
