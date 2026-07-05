# Loop闭环反馈系统实现计划

## 阶段：直接实现（无复杂子代理需要）

## 创建文件清单

1. `gmgn_monitor/loop_logging.py` — 结构化日志，JSONL格式，日志轮转
2. `gmgn_monitor/loop_engine.py` — 5个反馈循环引擎 + 依赖管理 + Kill Switch
3. `tests/test_loop_logging.py` — 日志模块测试（正常/异常路径）
4. `tests/test_loop_engine.py` — Loop引擎测试（5个循环/依赖/Kill Switch）

## 设计要点

### loop_logging.py
- `LoopLogger` 类：每个循环一个日志文件，JSONL结构化输出
- 自动按10MB大小轮转
- 使用 `file_io.durable_append_text` 保证写入安全
- `get_loop_logger()` 工厂函数

### loop_engine.py
- `LoopName` Enum：5个循环名称
- `LoopConfig` dataclass：所有阈值配置（支持default+覆盖模式）
- `LoopCheckResult` frozen dataclass：检查结果
- `BaseLoop` 基类：check / pause / resume / _now
- 5个具体循环类：
  - `DataQualityLoop`：数据完整性/缺失率/价格异常/连续失败
  - `ScoreValidationLoop`：Pearson相关系数/Top20变化/人工一致性
  - `BacktestCalibrationLoop`：7日偏差/滑点偏差
  - `ExecutionQualityLoop`：下单成功率/条件单触发率/MEV损失
  - `SystemHealthLoop`：服务可用性/内存/磁盘/余额
- `LoopEngine` 编排器：run_all / run_loop / _apply_dependencies / Kill Switch

### 测试
- pytest风格，覆盖所有正常/异常路径
- 使用tempfile避免污染真实日志目录
- 测试循环间依赖规则
- 测试Kill Switch全局暂停
- 测试日志轮转

## 编码风格约束
- `from __future__ import annotations`
- `dataclass(frozen=True)` 数据模型
- `pathlib.Path`
- 类型注解完整
- 标准库 only
- ruff line-length=120
