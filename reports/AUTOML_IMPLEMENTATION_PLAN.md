# AutoML 功能实现方案

## 1. 目标

在现有 `backtesting/enhanced_backtester.py` 的 `ParameterOptimizer` 基础上，集成更高级的“启发式”超参数搜索算法，以替代或补充现有的网格搜索（Grid Search），从而更高效地找到最优的策略参数组合。

## 2. 核心问题

- **网格搜索效率低下**：当参数维度增加或参数范围变大时，组合数量呈指数级增长，导致搜索时间过长。
- **无法处理连续参数**：网格搜索只能处理离散点，对于连续的浮点数参数（如 `divergence_rate`）无法进行精细搜索。
- **缺乏智能探索**：所有参数组合都被同等对待，无法根据历史结果动态调整搜索方向，将更多精力放在有潜力的参数空间。

## 3. 设计方案

### 3.1 技术选型：集成 `Optuna` 库

我们将引入业界领先的超参数优化框架 **`Optuna`**。

- **优势**：
    - **先进的采样算法**：内置基于 TPE（Tree-structured Parzen Estimator）的贝叶斯优化算法，能智能地在参数空间中进行探索和利用。
    - **灵活的参数定义**：轻松定义浮点数、整数、分类等多种类型的参数及其范围。
    - **高效的剪枝功能 (Pruning)**：可以提前终止没有希望的试验，大幅节省计算资源（此为 V2 功能，初期可不实现）。
    - **易于集成**：与现有代码结构耦合度低，可以无缝集成。
    - **强大的可视化**：提供丰富的可视化工具，帮助分析优化过程。

### 3.2 架构设计：扩展 `ParameterOptimizer`

我们将对 [`enhanced_backtester.py`](./backtesting/enhanced_backtester.py:473) 中的 `ParameterOptimizer` 类进行扩展，新增一个 `bayesian_search` 方法。

```python
# backtesting/enhanced_backtester.py

import optuna # 新增导入

class ParameterOptimizer:
    """策略参数优化器"""
    
    def __init__(self, base_config: Dict[str, Any], backtest_func: Callable, metric: str, direction: str = 'maximize'):
        """
        ... (构造函数更新) ...
        """
        self.base_config = base_config
        self.backtest_func = backtest_func # 运行一次回测的函数
        self.metric = metric             # 优化的目标指标
        self.direction = direction       # 优化方向: 'maximize' 或 'minimize'
        self.logger = logging.getLogger(__name__ + ".Optimizer")

    def grid_search(self, param_grid: Dict[str, List[Any]]) -> pd.DataFrame:
        """
        ... (现有网格搜索方法，保持不变) ...
        """
        pass

    def bayesian_search(self, param_space: Dict, n_trials: int, score_func: Callable = None) -> optuna.study.Study:
        """
        使用 Optuna 进行贝叶斯优化

        Args:
            param_space (Dict): 参数搜索空间定义
            n_trials (int): 优化的试验总次数
            score_func (Callable, optional): 自定义评分函数。
                                             输入为回测结果字典，输出为单一浮点数。
                                             如果为 None，则直接使用 self.metric 的值。

        Returns:
            optuna.study.Study: 包含所有试验结果的 Optuna study 对象
        """
        
        # 1. 定义目标函数 (Objective Function)
        def objective(trial: optuna.Trial) -> float:
            config = self.base_config.copy()

            # 2. 从搜索空间中动态建议参数
            for name, space in param_space.items():
                if space['type'] == 'float':
                    config[name] = trial.suggest_float(name, space['low'], space['high'])
                elif space['type'] == 'int':
                    config[name] = trial.suggest_int(name, space['low'], space['high'])
                elif space['type'] == 'categorical':
                    config[name] = trial.suggest_categorical(name, space['choices'])
            
            self.logger.info(f"Trial #{trial.number}: Testing params {trial.params}")

            try:
                # 3. 运行回测
                result = self.backtest_func(config)
                
                # 4. 计算最终得分
                if score_func:
                    score = score_func(result)
                else:
                    score = result.get(self.metric, 0.0)
                
                self.logger.info(f"Trial #{trial.number} result: {self.metric}={result.get(self.metric, 0.0):.4f}, Score={score:.4f}")
                
                return score

            except Exception as e:
                self.logger.error(f"Trial #{trial.number} failed: {e}")
                # 告诉 Optuna 这次试验失败了
                raise optuna.exceptions.TrialPruned()

        # 5. 创建并运行 Study
        study = optuna.create_study(direction=self.direction)
        study.optimize(objective, n_trials=n_trials)

        self.logger.info(f"Bayesian search finished. Best trial: {study.best_trial.value}")
        self.logger.info(f"Best params: {study.best_params}")

        return study
```

### 3.3 配置文件更新

为了支持 `Optuna` 更灵活的参数定义，我们将扩展 `param_grid.yaml` 的格式。

```yaml
# param_grid.yaml

# 缠论参数优化范围 (Optuna 格式)
param_space:
  # 浮点数类型: [类型, 下限, 上限]
  divergence_rate: 
    type: 'float'
    low: 0.8
    high: 1.2

  # 整数类型: [类型, 下限, 上限]
  macd_fast: 
    type: 'int'
    low: 8
    high: 16

  # 分类类型: [类型, [选项1, 选项2, ...]]
  bi_strict:
    type: 'categorical'
    choices: [true, false]

# 交易参数优化范围
trading_param_space:
  min_visual_score:
    type: 'int'
    low: 50
    high: 80
```

### 3.4 自定义评分函数

用户可以定义一个函数，将多个回测指标组合成一个最终的优化目标分数。

```python
# 示例：一个自定义评分函数
def custom_score_function(result: dict) -> float:
    """
    一个综合考虑回报率和回撤的评分函数
    """
    total_return = result.get('total_return_pct', 0.0)
    max_drawdown = result.get('max_drawdown_pct', 1.0) # 避免除以零

    # 我们希望回报率高，回撤低
    # 夏普比率的思想
    if max_drawdown < 0.01: # 如果回撤极小，给一个奖励
        return total_return
    
    score = total_return / max_drawdown
    
    # 对交易次数过少的策略进行惩罚
    if result.get('trades_count', 0) < 10:
        score *= 0.5
        
    return score
```

## 4. 数据库优化设计方案

鉴于当前 `Trade/db_util.py` 存在以下问题：
- 表结构存在不一致和冗余（`init_db` 和 `_init_database` 中有相似但不完全相同的表定义）。
- 每次数据库操作都会新建和关闭连接，存在性能开销。
- `config.yaml` 中虽支持 MySQL 配置，但实际 MySQL 实现缺失。

我们将按以下步骤进行数据库优化设计：

### 4.1 引入数据库抽象层 (`Trade/IDB.py`)

创建抽象基类 `IDB`，定义统一的数据库操作接口。这将确保不同数据库实现（SQLite/MySQL）具有一致的调用方式。

```python
# Trade/IDB.py (抽象接口)

import abc
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

class IDB(abc.ABC):
    """
    数据库操作接口定义
    """

    @abc.abstractmethod
    def init_db(self):
        """初始化数据库表结构和索引"""
        pass

    @abc.abstractmethod
    def execute_query(self, query: str, params: Tuple = ()) -> pd.DataFrame:
        """
        执行SQL查询并返回DataFrame
        """
        pass

    @abc.abstractmethod
    def execute_non_query(self, query: str, params: Tuple = ()) -> int:
        """
        执行非查询SQL（INSERT, UPDATE, DELETE）并返回受影响的行数
        """
        pass

    @abc.abstractmethod
    def save_signal(self, code: str, signal_type: str, score: float, chart_path: str, 
                    add_date: datetime, bstype: str, open_price: float, quota: float, 
                    model_score_before: float, status: str = 'active') -> int:
        """
        保存一个新的交易信号
        """
        pass

    @abc.abstractmethod
    def get_active_signals(self, code: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取所有活跃的信号
        """
        pass

    @abc.abstractmethod
    def update_signal_status(self, signal_id: int, new_status: str):
        """
        更新信号的状态
        """
        pass

    @abc.abstractmethod
    def save_order(self, code: str, action: str, quantity: int, price: float, 
                   order_status: str, signal_id: Optional[int] = None, 
                   add_time: datetime = datetime.now()) -> int:
        """
        保存一个订单记录
        """
        pass

    @abc.abstractmethod
    def get_pending_orders(self, code: str) -> List[Dict[str, Any]]:
        """
        获取指定股票的所有待处理订单
        """
        pass

    @abc.abstractmethod
    def update_order_status(self, order_id: int, new_status: str):
        """
        更新订单状态
        """
        pass

    @abc.abstractmethod
    def save_position(self, code: str, quantity: int, avg_cost: float, 
                      last_update: datetime = datetime.now()):
        """
        保存或更新持仓信息
        """
        pass

    @abc.abstractmethod
    def get_position(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取指定股票的持仓信息
        """
        pass

    @abc.abstractmethod
    def get_all_positions(self) -> List[Dict[str, Any]]:
        """
        获取所有持仓信息
        """
        pass

    @abc.abstractmethod
    def delete_position(self, code: str):
        """
        删除指定股票的持仓信息
        """
        pass

    @abc.abstractmethod
    def close(self):
        """
        关闭数据库连接
        """
        pass
```

### 4.2 重构 `Trade/db_util.py` 为 `Trade/SqliteDB.py` 并实现 `IDB` 接口

将当前 `Trade/db_util.py` 中的 SQLite 实现逻辑迁移到新的 `Trade/SqliteDB.py` 文件中，并使其实现 `IDB` 接口。

**关键修改点**：
- **统一表结构**：采用 `_init_database` 中定义的 `signals`, `orders`, `positions` 表结构，并确保与 `README.md` 中的 SQL 规范一致。移除冗余的表创建逻辑。
- **添加索引**：为 `signals` 表的 `code` 和 `status` 字段，`orders` 表的 `code` 和 `order_status` 字段，以及 `positions` 表的 `code` 字段添加索引，以加速查询。
- **连接池/单例模式**：实现数据库连接的单例模式，确保应用程序生命周期内只维护一个 SQLite 连接，避免频繁开关连接带来的性能损耗。

### 4.3 创建 `Trade/MysqlDB.py` (占位实现)

创建一个 `Trade/MysqlDB.py` 文件，使其实现 `IDB` 接口，但所有方法暂时抛出 `NotImplementedError`。这明确表示 MySQL 支持是未来的计划，但当前未实现。

### 4.4 创建 `Trade/db_manager.py` (数据库管理器)

创建一个 `Trade/db_manager.py` 文件，作为数据库操作的统一入口。

**主要职责**：
- 根据 `Config/EnvConfig.config` 中 `database.type` 的配置，动态选择并实例化 `SqliteDB` 或 `MysqlDB` (当前只会选择 SQLite)。
- 以单例模式提供数据库实例，确保整个应用共享同一个数据库连接（或连接池）。
- 外部模块通过 `db_manager` 提供的接口进行数据库操作，无需关心底层数据库类型和连接细节。

### 4.5 更新现有代码引用

- **移除 `Trade/db_util.py`**：在完成重构后，此文件将被删除。
- **更新所有对 `CChanDB` 的引用**：所有项目中对 `CChanDB` 的导入和实例化都将改为通过 `Trade/db_manager.py` 获取数据库实例。

## 5. 实施计划 (综合 AutoML 与数据库优化)

| 步骤 | 任务 | 涉及文件 | 优先级 |
|---|---|---|---|
| **数据库优化** ||||
| 1 | **创建 `Trade/IDB.py` 接口** | `Trade/IDB.py` | 高 |
| 2 | **重构 `Trade/db_util.py` 到 `Trade/SqliteDB.py` 并实现 `IDB`** | `Trade/db_util.py`, `Trade/SqliteDB.py` | 高 |
| 3 | **创建 `Trade/MysqlDB.py` 占位实现** | `Trade/MysqlDB.py` | 高 |
| 4 | **创建 `Trade/db_manager.py`** | `Trade/db_manager.py` | 高 |
| 5 | **更新所有 `CChanDB` 引用到 `db_manager`** | 全局，例如 `cn_stock_visual_trading.py`, `futu_hk_visual_trading_fixed.py`, `Monitoring/metrics.py` 等 | 高 |
| **AutoML 功能** ||||
| 6 | **添加 `Optuna` 依赖** | `requirements.txt` | 中 |
| 7 | **扩展 `ParameterOptimizer` (添加 `bayesian_search` 方法)** | `backtesting/enhanced_backtester.py` | 中 |
| 8 | **创建使用示例** | `scripts/run_optimizer.py` (新文件) | 中 |
| 9 | **更新 `param_grid.yaml` 以支持 Optuna 参数空间定义** | `param_grid.yaml` | 中 |
| 10 | **单元测试** | `backtesting/test_optimizer.py` (新文件) | 低 |
| **文档更新** ||||
| 11 | **更新 [`README.md`](./README.md:1) 和 [`backtesting/README.md`](./backtesting/README.md)** | `README.md`, `backtesting/README.md` | 中 |

---

## 6. 风险与缓解

- **依赖冲突**：`Optuna` 可能引入新的依赖，需要进行完整的环境测试。
- **性能问题**：回测函数本身的速度是瓶颈。AutoML 只是让搜索更智能，并不能减少单次回测的时间。需要告知用户这一点。
- **数据库迁移复杂性**：从直接使用 `sqlite3` 到通过抽象层进行操作，需要全面检查和测试所有数据库交互点。

## 7. Mermaid 流程图

### AutoML 优化流程

```mermaid
graph TD
    A[开始] --> B{加载基础配置和参数空间};
    B --> C[创建 Optuna Study];
    C --> D{循环 N 次试验};
    D --> E[Optuna 根据历史建议新参数];
    E --> F[运行一次完整回测];
    F --> G{计算自定义 Score};
    G --> H[将 (参数, Score) 结果返回给 Optuna];
    H --> D;
    D -- 完成 --> I[输出最优参数和最佳分数];
    I --> J[结束];
```

### 数据库抽象层架构

```mermaid
graph TD
    A[应用代码] --> B[Trade/db_manager.py];
    B --> C{根据配置选择数据库类型};
    C --> D[Trade/IDB.py (接口)];
    D --> E[Trade/SqliteDB.py (实现)];
    D --> F[Trade/MysqlDB.py (占位/未来实现)];
    E --> G[SQLite数据库文件];
    F --> H[MySQL数据库服务器];