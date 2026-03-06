# GUI 功能增强计划：单股数据修复

## 1. 需求背景

用户提出新需求：在 `ashare_bsp_scanner_gui.py` 的主界面中，为“单只股票分析”功能区增加一个按钮，用于手动触发对当前输入股票的历史数据进行补齐。

## 2. 目标

- 在GUI界面上增加一个“补全数据”按钮。
- 点击该按钮后，程序会在后台为指定的单个股票下载并补充从2024年1月1日至今的所有时间级别（`day`, `30m`, `5m`, `1m`）的K线数据。
- 整个过程不能阻塞GUI主线程，并需要向用户提供清晰的状态反馈。

## 3. 技术方案

我们将利用现有的 `PyQt6` 框架和 `QThread` 线程模型，结合 `repair_data.py` 中已有的数据修复逻辑来实现此功能。

### 3.1. 界面修改

- **文件**: `App/ashare_bsp_scanner_gui.py`
- **定位**: `create_left_panel` 方法中的“单只股票分析” `QGroupBox`。
- **操作**:
    1. 在现有的“分析”按钮 (`self.analyze_btn`) 旁边，新增一个 `QPushButton`，对象命名为 `self.repair_btn`，显示文本为“补全数据”。
    2. 将此按钮的 `clicked` 信号连接到一个新的槽函数，例如 `self.repair_single_stock`。

### 3.2. 后台修复任务

- **新建线程类**: 创建一个新的 `QThread` 子类，命名为 `RepairSingleStockThread`。
- **职责**:
    - 接收 `stock_code` 作为初始化参数。
    - 其 `run` 方法将导入并调用 `repair_data.py` 中的 `diagnose_and_repair_stock` 函数。
    - 将会为传入的 `stock_code` 依次检查和修复所有核心时间级别 (`['day', '30m', '5m', '1m']`) 的数据。
    - **日期范围**: 硬编码为从 "2024-01-01" 到当前日期。
    - **信号**: 定义 `log_signal(str)` 和 `finished_signal(bool, str)` 信号，用于向主线程报告进度和最终结果。

### 3.3. 主线程逻辑 (控制与反馈)

- **新建槽函数**: 创建 `repair_single_stock(self)` 方法。
- **职责**:
    1. 从 `self.code_input` 获取股票代码并进行标准化。
    2. 验证代码是否为空。
    3. **禁用相关按钮**: 设置 `self.analyze_btn.setEnabled(False)` 和 `self.repair_btn.setEnabled(False)`，防止用户重复点击。
    4. 更新状态栏信息为“正在补全数据...”。
    5. 实例化 `RepairSingleStockThread` 并启动它。
    6. 将线程的 `log_signal` 连接到 `self.on_log_message`，将 `finished_signal` 连接到一个新的完成处理函数 `on_repair_finished`。

- **新建完成处理函数**: 创建 `on_repair_finished(self, success, message)` 方法。
- **职责**:
    1. **恢复按钮**: 重新启用 `self.analyze_btn` 和 `self.repair_btn`。
    2. 更新状态栏信息。
    3. 弹出一个 `QMessageBox`，告知用户“数据补全完成”或“补全失败”及原因。

## 4. 实施步骤

1.  **添加UI元素**: 在 `create_left_panel` 方法中，找到 `code_row` 布局，在 "分析" 按钮后添加 "补全数据" 按钮。
2.  **创建 `RepairSingleStockThread` 类**: 在 `ashare_bsp_scanner_gui.py` 文件中，仿照 `UpdateDatabaseThread` 的结构创建新线程类。
3.  **实现 `run` 方法**: 在新线程的 `run` 方法中，`from repair_data import diagnose_and_repair_stock`，然后在一个循环中为每个 `timeframe` 调用该函数，并包裹 `try-except` 块来捕获异常并通过信号发送。
4.  **实现 `repair_single_stock` 方法**: 编写按钮点击后触发的控制逻辑。
5.  **实现 `on_repair_finished` 方法**: 编写任务完成后恢复UI状态和提醒用户的逻辑。
6.  **连接信号与槽**: 在 `init_ui` 或 `repair_single_stock` 中完成信号和槽的连接。

## 5. Mermaid 流程图

```mermaid
graph TD
    subgraph 用户界面
        A[用户点击 "补全数据" 按钮] --> B{repair_single_stock() 槽函数};
    end

    subgraph 主线程
        B --> C{获取股票代码};
        C --> D[禁用 "分析" 和 "补全数据" 按钮];
        D --> E[更新状态栏: "正在补全..."];
        E --> F[创建并启动 RepairSingleStockThread];
        F --> G{监听线程信号};
    end

    subgraph 后台线程 (RepairSingleStockThread)
        H[线程开始] --> I{循环遍历 timeframes};
        I --> J{调用 diagnose_and_repair_stock()};
        J --> K[发送 log_signal];
        K --> I;
        I -- 循环结束 --> L[发送 finished_signal];
        L --> M[线程结束];
    end

    G -- log_signal --> N[on_log_message(): 更新日志区域];
    G -- finished_signal --> O{on_repair_finished()};
    O --> P[恢复按钮];
    P --> Q[更新状态栏];
    Q --> R[弹出 QMessageBox 提示结果];

```
