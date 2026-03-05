# 集成富途 API 实现盘中实时订阅与增量计算方案 (v2)

## 1. 背景与目标

遵照您的明确指示，我们将放弃基于 `akshare` 的轮询方案，并采纳您最初建议的**方案三**：直接集成**富途 API**，利用其原生的“**订阅与推送 (Subscribe & Push)**”机制来实现真正的盘中实时监控。

**核心需求更新**：根据您的最新反馈，本方案将实现**自动从用户的富途客户端获取其“自选股”分组**，作为监控的股票池，取代手动输入代码。

## 2. 架构设计

-   **自选股获取**：程序启动或用户手动刷新时，通过富途 API 的 `get_user_security_group_list` 接口获取用户所有自定义的自选股板块。
-   **数据预加载**：用户选择一个自选股板块并开始监控时，利用已建成的 **SQLite 本地数据库**快速加载该板块内所有股票的初始化历史K线。
-   **实时数据流**：连接到富途 OpenAPI，订阅用户所选自选股板块内所有股票的实时 K 线（例如 1 分钟级别）。
-   **增量计算**：当富途服务器推送新的 K 线数据时，程序会接收到该数据，并将其**追加**到对应的 `CChan` 对象中，触发**增量式**的缠论结构计算。
-   **信号反馈**：一旦增量计算产生了新的买卖点，立即通过 UI 界面发出通知。

## 3. 实施计划

### 第一步：环境配置与依赖 (无变化)

1.  **添加依赖**：确保项目中已安装 `futu-api` 库。
2.  **更新配置**：在 `Config/config.yaml` 或类似配置文件中，增加富途 OpenAPI 的连接参数。

### 第二步：创建 `FutuMonitor` 核心监控类 (功能增强)

在 `Monitoring/FutuMonitor.py` 中，扩展 `FutuMonitor` 类的功能：

-   `__init__(self, config)`：(无变化) 初始化时，读取配置并建立与富途网关的连接。
-   `get_watchlists(self) -> list`: **(新增)** 调用 `self.quote_ctx.get_user_security_group_list()` 获取所有自选股分组的名称列表。
-   `set_callback(self, ui_callback)`：(无变化) 设置一个回调函数，用于将监控结果发送回 UI 线程。
-   `start(self, watchlist_name: str)`：**(逻辑修改)**
    -   接收一个**自选股分组名称**作为参数。
    -   调用 `self.quote_ctx.get_user_security_group(group_name=watchlist_name)` 获取该分组下的股票代码列表。
    -   对每个代码，首先从本地 SQLite 数据库加载历史数据，创建 `CChan` 实例并缓存。
    -   调用富途 API 的 `subscribe()` 方法，订阅这些代码的 `SubType.K_1M`。
    -   设置富途 API 的回调处理器 `self.quote_ctx.set_on_recv_rsp(self.on_recv_rsp)`。
-   `on_recv_rsp(self, rsp)`：(无变化) 接收富途实时推送数据的核心。
-   `stop(self)`：(无变化) 取消所有订阅，并安全断开与富途网关的连接。

### 第三步：GUI 集成 (界面修改)

1.  **修改 UI 面板**：在 `ashare_bsp_scanner_gui.py` 的“Futu 实时监控”面板中，做如下修改：
    -   移除手动输入股票代码的 `QLineEdit`。
    -   增加一个 `QComboBox` (下拉列表)，用于展示从富途获取的自选股分组。
    -   增加一个“刷新列表” `QPushButton`，点击后调用 `FutuMonitor.get_watchlists()` 并将结果更新到 `QComboBox` 中。
2.  **修改控件逻辑**：
    -   “开始监控”按钮的逻辑改为：获取当前 `QComboBox` 中选中的自选股分组名称，并将其作为参数传递给 `FutuMonitor.start()` 方法。
    -   其他部分（线程管理、信号与槽连接）保持不变。

## 4. 技术方案示意图 (Mermaid)

```mermaid
graph TD
    subgraph GUI 线程
        A[用户点击 "刷新列表"] --> B[FutuMonitor.get_watchlists()];
        B --> C[更新自选股下拉框];
        C --> D[用户从下拉框选择一个自选股分组];
        D --> E[点击 "开始监控"];
        E --> F[启动 FutuThread];
        F --> G[FutuMonitor.start(所选分组名)];
        H[UI 日志窗口];
    end
    
    subgraph FutuThread (后台线程)
        G --> I[1. FutuAPI.get_user_security_group 获取组内代码];
        I --> J[2. 从 SQLite 加载历史K线];
        J --> K[3. 初始化 CChan 对象];
        K --> L[4. FutuAPI.subscribe(codes)];
        L --> M{等待富途服务器推送...};
        M -- 新K线数据 --> N[on_recv_rsp 回调];
        N --> O[chan.append_kl() 增量计算];
        O -- 发现新信号 --> P[通过回调/信号机制];
    end
    
    subgraph GUI 线程
        P --> H;
    end
```

此方案集成了您所有的需求，提供了一个无缝、便捷且功能强大的盘中监控工作流。