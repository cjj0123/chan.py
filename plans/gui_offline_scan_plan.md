# A股扫描器 GUI 离线扫描与并发优化方案 (SQLite 版)

## 1. 需求分析

当前 `App/ashare_bsp_scanner_gui.py` 在扫描过程中，为每只股票实时通过 `akshare` API 获取 K 线数据。这种模式存在以下问题：

- **性能瓶颈**：串行获取大量股票的 K 线数据非常耗时，一次全市场扫描可能需要数小时。
- **并发限制**：如果强行改为并发，会因高频 API 请求而被 `akshare` 或其底层数据源封禁 IP。
- **功能缺失**：缺少对历史数据进行大规模、快速回测和研究的能力。

根据讨论，我们决定采用**方案一：“离线下载 + 本地扫描”模式**，并选用 **SQLite**作为本地数据存储方案，以复用项目中已有的数据库能力（如 `Trade/db_util.py`）。

## 2. 核心目标

将 `ashare_bsp_scanner_gui.py` 改造为支持**在线（实时）**和**离线（本地 SQLite 数据库）**两种数据源模式，并为离线模式提供数据下载功能，从根本上解决扫描性能问题。

## 3. 实施计划

我们将分步对现有 GUI 程序进行模块化增强，具体步骤如下：

### 第一步：增强 UI，增加模式切换选项

在扫描设置区域，增加一个数据源切换的下拉框，允许用户选择：

- **在线模式 (Akshare)**：保留现有逻辑，实时从网络获取数据。
- **离线模式 (SQLite)**：从本地 `chan_trading.db` 数据库中读取预先下载好的K线数据。

同时，在 UI 中增加一个“**更新本地数据库**”的按钮，用于触发数据下载流程。

### 第二步：实现离线数据下载与存储模块

1.  **扩展数据库结构**：修改 `Trade/db_util.py` 中的 `CChanDB` 或创建一个新的工具类，在数据库中创建一张用于存储日线 K 线数据的表，例如 `kline_day`。表结构应包含 `code`, `date`, `open`, `high`, `low`, `close`, `volume` 等字段。
2.  **创建数据下载线程**：创建一个新的后台线程 `DownloadThread`，负责：
    -   调用 `get_tradable_stocks()` 获取完整的A股列表。
    -   遍历每只股票，使用 `akshare` 下载其日线历史数据。
    -   将下载的 `DataFrame` 数据批量存入 `kline_day` 表中，使用 `df.to_sql` 的 `if_exists='replace'` 模式可以高效地插入或更新数据。
    -   在 UI 上通过进度条和日志实时反馈下载进度。

### 第三步：改造扫描逻辑以支持双模式

1.  **创建 `SQLiteDataAPI`**：在 `DataAPI/` 目录下创建一个新的 `SQLiteAPI.py` 文件，实现一个自定义的 `CStockAPI` 接口。这个类中的 `get_kl_data` 方法将从 SQLite 数据库中查询指定股票和时间范围的 K 线数据并返回 `DataFrame`。
2.  **重构 `start_scan` 和 `ScanThread`**：
    -   **`start_scan`**：
        -   **在线模式**：调用 `get_tradable_stocks()` 从网络获取股票列表。
        -   **离线模式**：通过执行 `SELECT DISTINCT code FROM kline_day` 从数据库中获取已缓存的股票列表。
    -   **`ScanThread.run`**：
        -   根据模式选择，在实例化 `CChan` 时传入不同的 `data_src`：
            -   **在线模式**：`data_src=DATA_SRC.AKSHARE`。
            -   **离线模式**：`data_src=DATA_SRC.CUSTOM`，并传入 `custom_api=SQLiteAPI()` 的实例。

### 第四步：单股分析功能适配

同样地，`analyze_single` 方法也需要根据当前选择的数据源模式，来决定是通过 `akshare` 实时分析，还是从本地 SQLite 数据库加载数据进行分析。

## 4. 技术方案示意图 (Mermaid)

```mermaid
graph TD
    subgraph 用户操作
        A[启动扫描器 GUI] --> B{选择数据源};
        B -- "在线模式 (Akshare)" --> C[点击 "开始扫描"];
        B -- "离线模式 (SQLite)" --> D[点击 "更新本地数据库" (首次)];
        D --> E[等待数据下载完成];
        E --> F[点击 "开始扫描"];
        B -- "离线模式 (SQLite)" --> F;
    end

    subgraph 程序逻辑
        C --> G[ScanThread: 实时获取股票列表];
        G --> H[循环内: CChan(data_src=AKSHARE)];
        
        F --> I[ScanThread: 从 SQLite 获取股票列表];
        I --> J[循环内: CChan(data_src=CUSTOM, custom_api=SQLiteReader)];

        H --> K[发出买点信号];
        J --> K;
    end

    subgraph 最终结果
        K --> L[更新UI买点列表];
    end
```

## 5. 预期成果

- 利用项目现有数据库能力，避免引入新的文件格式依赖。
- **离线模式**下，全市场扫描速度将从数小时级别提升至分钟级别。
- 数据集中管理在单个数据库文件中，便于备份和迁移。
- 代码结构更加清晰，数据获取与数据分析逻辑分离。
