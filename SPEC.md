# GMGN 扫链聪明钱包发现 + 自动化跟单系统 — SPEC

> **版本**: v1.0  
> **日期**: 2026-07-03  
> **状态**: 设计阶段（待评审）  
> **核心目标**: 通过 Loop Engineering 模式，分阶段构建从"钱包发现"到"自动跟单"的闭环系统

---

## 目录

1. [项目概述与总体架构](#1-项目概述与总体架构)
2. [Loop Engineering 总纲](#2-loop-engineering-总纲)
3. [阶段1：钱包发现 + 评分 + 回测](#3-阶段1钱包发现--评分--回测)
4. [阶段2：API接入 + 自动化跟单](#4-阶段2api接入--自动化跟单)
5. [数据流与接口定义](#5-数据流与接口定义)
6. [实施路线图与里程碑](#6-实施路线图与里程碑)
7. [附录](#7-附录)

---

## 1. 项目概述与总体架构

### 1.1 项目背景

基于对 GMGN 生态的深度研究（80+次搜索、8维度并行挖掘、14个子代理协作），本系统旨在解决 Meme 交易中的核心问题：

- **98.6% 的代币归零** — 需要智能筛选，而非随机赌博
- **仅 40% 月赚钱** — 需要量化验证，而非主观判断
- **1% 手续费侵蚀** — 需要低频高确定性策略
- **前 100 名获利 300%，后续亏损 82%** — 需要信息优势和速度优势

### 1.2 两阶段架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         GMGN 扫链聪明钱包系统                              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                      阶段1：发现 + 验证                              │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐      │   │
│  │  │ 数据抓取  │ → │ 钱包筛选  │ → │ 评分引擎  │ → │ 模拟回测  │      │   │
│  │  │ Pipeline │   │ 过滤规则  │   │ 5维加权  │   │ 3种策略  │      │   │
│  │  └──────────┘   └──────────┘   └──────────┘   └──────────┘      │   │
│  │         │              │              │              │           │   │
│  │         └──────────────┴──────────────┴──────────────┘           │   │
│  │                            │                                     │   │
│  │                            ▼                                     │   │
│  │                    ┌────────────┐                               │   │
│  │                    │ 白名单输出  │  → 合格钱包 + 策略参数         │   │
│  │                    └────────────┘                               │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                                    ▼ (Go/No-Go 决策)                    │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                      阶段2：执行 + 风控                              │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐      │   │
│  │  │ API接入   │ → │ 信号引擎  │ → │ 自动执行  │ → │ 风控监控  │      │   │
│  │  │ 数据管道 │   │ 意图识别  │   │ 订单管理  │   │ 熔断机制  │      │   │
│  │  └──────────┘   └──────────┘   └──────────┘   └──────────┘      │   │
│  │         │              │              │              │           │   │
│  │         └──────────────┴──────────────┴──────────────┘           │   │
│  │                            │                                     │   │
│  │                            ▼                                     │   │
│  │                    ┌────────────┐                               │   │
│  │                    │ Loop闭环   │  ← 自我修正反馈                │   │
│  │                    └────────────┘                               │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ 底层支撑：数据存储 (SQLite/JSONL) + 配置管理 + 监控告警 + 审计日志      │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.3 设计原则

| 优先级 | 原则 | 说明 |
|:---:|:---|:---|
| P0 | **本金安全** | 任何情况下不允许单笔亏损超过预设阈值，不允许每日亏损超过硬限制 |
| P0 | **渐进暴露** | 观察 → 模拟 → 小额实盘 → 全量，每步必须通过验收 |
| P1 | **可验证性** | 所有策略必须回测验证，不接受"感觉良好"的决策 |
| P1 | **最小权限** | 私钥隔离、操作可撤销、自动化权限逐级放开 |
| P2 | **透明可解释** | 每笔交易必须有完整的决策日志、风控校验记录、回测支撑 |
| P2 | **可回滚** | 所有可调参数带版本号，支持一键回滚，变更审计 |

### 1.4 技术栈总览

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 数据抓取 | Python + GmGnAPI (pip) + gmgn-cli (npm) | 双源冗余，限速 2次/秒 |
| 评分引擎 | pandas + numpy + scipy | 6维加权评分，支持权重自优化 |
| 回测引擎 | pandas + 自定义 Walk-Forward | 三种买入模式，含费用模型 |
| 信号引擎 | Python WebSocket + REST 轮询 | 自动重连、心跳保活、断线告警 |
| 自动执行 | gmgn-cli (cooking + multi-swap) | 条件单、止盈止损、多钱包并发 |
| 数据存储 | SQLite (WAL模式) + JSONL + Redis | 关系数据 + 事件流 + 缓存 |
| 监控告警 | systemd + 飞书/钉钉 webhook | 分级告警，P0 < 30秒 |
| 密钥管理 | 权限600的 ~/.config/gmgn/.env | 环境变量注入，代码仓库无密钥 |
| 测试 | pytest + mypy + ruff | 单元测试覆盖率 ≥ 80% |

---

## 2. Loop Engineering 总纲

### 2.1 核心理念

继承 [stockconsult](https://github.com/henry/stockconsult) 项目的 Loop Engineering 经验，本系统部署 **5 个自修复反馈循环**，每个循环都有：检查指标 → 触发条件 → 自动修正 → 验收验证。

```
┌─────────────────────────────────────────────────────────────┐
│                    Loop Engineering 五闭环                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐            │
│   │ Loop 1   │    │ Loop 2   │    │ Loop 3   │            │
│   │ 数据质量  │◄──►│ 评分校验  │◄──►│ 回测校准  │            │
│   │ 1分钟    │    │ 每日     │    │ 每日     │            │
│   └──────────┘    └──────────┘    └──────────┘            │
│        │               │               │                    │
│        ▼               ▼               ▼                    │
│   ┌──────────┐    ┌──────────┐                            │
│   │ Loop 4   │    │ Loop 5   │                            │
│   │ 执行质量  │◄──►│ 系统健康  │                            │
│   │ 每笔交易  │    │ 每5分钟  │                            │
│   └──────────┘    └──────────┘                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 五闭环详细定义

#### Loop 1：数据质量闭环（频率：1分钟）

| 维度 | 定义 |
|------|------|
| **检查指标** | 数据完整性率、重复率、缺失率、价格异常率 |
| **触发条件** | 连续 3 次抓取失败 / 字段缺失率 > 5% / 价格偏离 > 20% |
| **自动修正** | 暂停 → 重抓 → 切换备用源（gmgn-cli）→ 恢复 |
| **验收验证** | 修正后数据完整性率 ≥ 95% |
| **日志位置** | `logs/loop/data_quality.log` |

#### Loop 2：评分校验闭环（频率：每日）

| 维度 | 定义 |
|------|------|
| **检查指标** | 评分-收益 Pearson 相关系数、Top 20 评分变化率、人工标注一致性 |
| **触发条件** | r < 0.6 / Top 20 评分变化 > 15% / 人工一致性 < 75% |
| **自动修正** | 自动触发权重网格搜索（调整幅度 ≤ 5%）→ 重新评分 → 验证 |
| **验收验证** | 修正后 r ≥ 0.6，人工一致性 ≥ 75% |
| **日志位置** | `logs/loop/scoring_validation.log` |

#### Loop 3：回测校准闭环（频率：每日/每笔执行）

| 维度 | 定义 |
|------|------|
| **检查指标** | 模拟收益 vs 实际收益偏差、滑点估计偏差、胜率偏差 |
| **触发条件** | 7 日偏差 > 20% / 单笔滑点偏差 > 30% |
| **自动修正** | 自动调整滑点参数（幅度 ≤ 5%）→ 重新回测 → 验证 |
| **验收验证** | 偏差 < 15% |
| **日志位置** | `logs/loop/backtest_calibration.log` |

#### Loop 4：执行质量闭环（频率：每笔交易）

| 维度 | 定义 |
|------|------|
| **检查指标** | 下单成功率、条件单触发率、滑点实际值、MEV 损失率 |
| **触发条件** | 下单成功率 < 95% / 条件单触发 < 99% / MEV 损失 > 1% |
| **自动修正** | 自动切换 RPC / 调整滑点模式 / 切换 MEV 防护等级 |
| **验收验证** | 下单成功率 > 95%，条件单触发 > 99% |
| **日志位置** | `logs/loop/execution_quality.log` |

#### Loop 5：系统健康闭环（频率：每5分钟）

| 维度 | 定义 |
|------|------|
| **检查指标** | 服务可用性、内存/CPU、磁盘空间、日志健康、钱包余额 |
| **触发条件** | 服务不可用 / 内存 > 80% / 磁盘 > 90% / 余额 < 阈值 |
| **自动修正** | 服务重启 / 清理缓存 / 告警 / 暂停交易 |
| **验收验证** | 服务恢复 < 2 分钟，告警 < 1 分钟 |
| **日志位置** | `logs/loop/system_health.log` |

### 2.3 闭环间的联动规则

```
Loop 1 (数据质量) 异常 ──► 暂停 Loop 2/3/4，只保留 Loop 5
Loop 2 (评分校验) 异常 ──► 触发 Loop 3 重新回测，暂停 Loop 4
Loop 3 (回测校准) 异常 ──► 触发权重自优化 (Loop 2)，暂停 Loop 4
Loop 4 (执行质量) 异常 ──► 触发风控熔断 (Loop 5)，暂停新交易
Loop 5 (系统健康) 异常 ──► 全局 Kill Switch，所有交易暂停
```

---

## 3. 阶段1：钱包发现 + 评分 + 回测

### 3.1 阶段1目标

建立高质量聪明钱包的自动化发现、评分、回测体系，输出经过验证的钱包白名单与策略参数，为阶段2提供决策输入。

**安全边界**：阶段1全程不引入私钥、签名或链上交易提交。所有"交易"均为本地模拟。

### 3.2 子目标总览

| 编号 | 子目标 | 核心指标 | 周期 | 详细文档 |
|------|--------|----------|------|----------|
| 1.1 | 数据抓取基础设施 | 成功率 ≥ 95%，限速 2次/秒 | 2天 | [详细设计](阶段1-钱包发现与数据收集.md) |
| 1.2 | 钱包候选池构建 | 5,000+ 活跃地址，淘汰率 ≥ 80% | 1天 | [详细设计](阶段1-钱包发现与数据收集.md) |
| 1.3 | 多维度评分引擎 | 5维加权，0-100分，延迟 < 50ms | 3天 | [详细设计](阶段1-评分体系与质量筛选.md) |
| 1.4 | 质量筛选与过滤 | 10+ 规则，机器人识别 ≥ 90% | 3天 | [详细设计](阶段1-评分体系与质量筛选.md) |
| 1.5 | 模拟回测引擎 | 3种策略，90天历史，夏普/回撤 | 5天 | [详细设计](阶段1-模拟跟单与回测引擎.md) |
| 1.6 | 评分验证与调优 | 200+样本，人工一致 ≥ 75% | 5天 | [详细设计](阶段1-模拟跟单与回测引擎.md) |
| 1.7 | Dashboard集成 | 与现有系统无缝集成 | 4天 | [详细设计](阶段1-模拟跟单与回测引擎.md) |

### 3.3 核心数据模型

```python
# Wallet 核心实体
class WalletScore(BaseModel):
    address: str                    # 钱包地址
    score: float                  # 综合评分 0-100
    tier: Literal["S","A","B","C","D"]  # 等级
    
    # 六维度评分
    profitability: float          # 盈利能力 25%
    win_rate: float               # 胜率 20%
    risk_control: float           # 风险控制 20%
    consistency: float            # 一致性 15%
    activity: float               # 活跃度 10%
    stability: float              # 稳定性 10%
    
    # 元数据
    total_pnl: float              # 总盈亏
    trade_count: int              # 交易笔数
    avg_hold_time: float          # 平均持仓时间(小时)
    golden_dog_count: int         # 捕获金狗数量
    robot_score: float            # 机器人嫌疑分 0-100
    last_updated: datetime

class BacktestResult(BaseModel):
    wallet_address: str
    strategy: Literal["fixed_buy","max_buy","fixed_ratio"]
    period_days: int              # 回测周期
    
    # 收益指标
    total_return: float           # 总收益率
    sharpe_ratio: float           # 夏普比率
    max_drawdown: float           # 最大回撤
    win_rate: float               # 胜率
    
    # 费用模型
    fee_cost: float               # 手续费成本
    slippage_cost: float          # 滑点成本
    net_return: float             # 扣除费用后净收益
    
    # 验证指标
    expectancy: float             # 期望值
    profit_factor: float          # 盈亏比
    trades_executed: int          # 执行交易数
```

### 3.4 评分公式

```python
# 六维加权评分（权重可配置，支持自优化）
SCORE = (
    profitability * 0.25 +
    win_rate * 0.20 +
    risk_control * 0.20 +
    consistency * 0.15 +
    activity * 0.10 +
    stability * 0.10
)

# 各维度计算方式
profitability = normalize(total_pnl, min=0, max=100000) * 100
win_rate = (winning_trades / total_trades) * 100
risk_control = (1 - max_drawdown) * 100  # 最大回撤越小越好
consistency = 1 / std(daily_returns) * 100  # 收益波动越小越好
activity = normalize(trade_count, min=10, max=100) * 100  # 每周10-100笔为最佳
stability = (stablecoin_ratio) * 100  # 持有稳定币比例反映纪律性

# 机器人过滤（一票否决）
if robot_score > 60:  # 7天交易>500次 / 交易间隔过于一致 / 无持仓时间
    score = 0
    tier = "D"
    reason = "ROBOT_DETECTED"
```

### 3.5 回测策略参数

| 策略 | 买入规则 | 止盈规则 | 止损规则 | 适用场景 |
|------|---------|---------|---------|---------|
| **Fixed Buy** | 固定 0.5-1 SOL/笔 | +100%卖50%, +300%卖剩余50% | -65%全卖 | 新手首选，风险可控 |
| **Max Buy** | 设置上限，源钱包超限时按上限 | 2X卖50%, 5X卖30%, 剩余20%持有 | -40%全卖 | 保守策略，大资金 |
| **Fixed Ratio** | 按源钱包仓位 10-20% 镜像 | 追踪止盈（回撤10%触发） | 追踪止损（回撤15%触发） | 激进策略，需高信心 |

**费用模型**（保守估计）：
- 手续费：1%（双向 = 2%）
- 滑点：日常 20-30%，热门盘 30-50%
- 优先费：0.01-0.03 SOL（标准），0.05-0.1 SOL（竞争激烈）

### 3.6 阶段1 Go/No-Go 决策

```
阶段1 输出验收:
├── 数据质量检查: 完整性 ≥ 95% ?
├── 评分质量检查: 人工一致性 ≥ 75%, r ≥ 0.6 ?
├── 回测结果检查: 夏普 ≥ 0.5, 回撤 ≤ 40%, 胜率 ≥ 55% ?
├── 过拟合检查: 训练集 vs 测试集偏差 < 15% ?
├── 安全合规检查: 无私钥泄露, 无自动交易 ?
└── Loop 闭合检查: 5个闭环运行 ≥ 7 天无报错 ?
    
    全部通过 → Go → 进入阶段2
    任一失败 → No-Go → 回退到对应子目标重新调优
```

---

## 4. 阶段2：API接入 + 自动化跟单

### 4.1 阶段2目标

接入 GMGN API 和链上执行能力，实现从信号监听到自动执行的完整链路，同时部署多层风控和资金管理。

**安全边界**：阶段2引入私钥和链上交易，必须严格遵循"渐进暴露"原则。

### 4.2 子目标总览

| 编号 | 子目标 | 核心指标 | 周期 | 详细文档 |
|------|--------|----------|------|----------|
| 2.1 | API接入与数据管道 | P95 延迟 < 3秒，丢包 < 0.1% | 2周 | [详细设计](阶段2-API接入与数据管道.md) |
| 2.2 | 信号预处理与过滤 | 过滤准确率 > 95%，误过滤 < 5% | 1周 | [详细设计](阶段2-自动化跟单执行引擎.md) |
| 2.3 | 跟单决策引擎 | CSS 计算延迟 < 200ms，胜率 > 50% | 2周 | [详细设计](阶段2-自动化跟单执行引擎.md) |
| 2.4 | 交易执行器 | 下单成功率 > 95%，条件单 100% | 2周 | [详细设计](阶段2-自动化跟单执行引擎.md) |
| 2.5 | 实时风控与熔断 | 触发后 10秒停单，日亏损 < 10% | 1.5周 | [详细设计](阶段2-风控系统与资金管理.md) |
| 2.6 | 持仓管理与盈亏追踪 | 链上一致性误差 < 0.1% | 1.5周 | [详细设计](阶段2-风控系统与资金管理.md) |
| 2.7 | 监控与告警 | P0 告警 < 30秒，覆盖率 100% | 1周 | [详细设计](阶段2-风控系统与资金管理.md) |
| 2.8 | 模拟交易模式 | 与真实趋势 Pearson > 0.9 | 1周 | [详细设计](阶段2-API接入与数据管道.md) |

### 4.3 核心数据模型

```python
class TradeSignal(BaseModel):
    signal_id: str                  # 唯一信号ID
    wallet_address: str             # 源钱包（聪明钱）
    target_token: str               # 目标代币
    signal_type: Literal["NEW_POSITION","ADD_POSITION","REDUCE","EXIT"]
    
    # 信号质量
    urgency_score: int              # 紧急程度 0-100
    confidence_score: int           # 置信度 0-100
    quality_score: int              # 综合质量 0-100
    
    # 交易参数
    recommended_amount: float     # 推荐买入金额(SOL)
    max_slippage: float             # 最大滑点(%)
    priority_fee: float             # 优先费(SOL)
    mev_protection: Literal["OFF","REDUCED","SECURE"]
    
    # 条件单
    tp_orders: list[TPOrder]      # 止盈订单列表
    sl_order: SLOrder               # 止损订单
    expires_at: datetime            # 信号过期时间（默认10分钟）

class TradeExecution(BaseModel):
    execution_id: str
    signal_id: str
    status: Literal["PENDING","SUBMITTED","CONFIRMED","FAILED","CANCELLED"]
    
    # 执行结果
    tx_hash: Optional[str]
    actual_amount: float            # 实际买入金额
    actual_slippage: float          # 实际滑点
    gas_cost: float                 # Gas费用
    mev_loss: Optional[float]       # MEV损失
    
    # 时间戳
    received_at: datetime
    decided_at: datetime
    submitted_at: datetime
    confirmed_at: Optional[datetime]
```

### 4.4 CSS 决策评分模型

```python
# 综合决策评分 (Comprehensive Signal Score)
CSS = (
    wallet_score * 0.25 +      # 钱包评分（来自阶段1）
    token_risk * 0.20 +         # 代币风险（市值、流动性、合约安全）
    market_condition * 0.15 +   # 市场环境（BTC走势、整体情绪）
    account_state * 0.20 +      # 账户状态（余额、持仓、日亏损）
    time_momentum * 0.20        # 时间动量（信号新鲜度、链上活跃度）
)

# 执行决策
if CSS >= 70 and account_state.can_trade:
    execute_trade()
elif CSS >= 50 and account_state.can_trade:
    queue_for_review()  # 人工审核队列
else:
    reject_signal()
```

### 4.5 风控红线

| 规则 | 触发条件 | 动作 | 不可撤销 |
|------|---------|------|---------|
| 单笔止损 | 亏损达到 -30% ~ -65% | 自动卖出 100% | ✅ |
| 日亏损上限 | 日亏损达到本金的 5% | 当日禁止开新仓 | ✅ |
| 周亏损上限 | 周亏损达到本金的 15% | 暂停交易，人工审核 | ✅ |
| 持仓上限 | 单钱包持仓超过 5 个代币 | 新信号自动排队 | ✅ |
| 余额不足 | 余额连续 3 次不足 | 自动停止跟单 | ✅ |
| 代币黑名单 | 貔貅/延迟貔貅/黑名单 | 禁止交易，告警 | ✅ |
| 系统熔断 | 连续 3 笔失败 / 异常交易 | 全局暂停，告警 | ✅ |

### 4.6 渐进暴露路线图

```
第 1-2 周: 观察级（0 SOL）
   └── 只监控，不交易。验证信号质量和延迟。
   
第 3-4 周: 模拟级（0.5 SOL/笔）
   └── 模拟交易，验证回测准确性。
   
第 5-6 周: 小额实盘（0.5-1 SOL/笔）
   └── 真实交易，单日上限 100 USDC，单笔上限 50 USDC。
   
第 7-8 周: 全量级（1-2 SOL/笔）
   └── 逐步放开，单日上限 1000 USDC，单笔上限 500 USDC。
   
第 9+ 周: 优化迭代
   └── 基于 Loop Engineering 反馈，持续调优。
```

### 4.7 阶段2 Go/No-Go 决策

```
阶段2 输出验收:
├── 信号质量: 准确率 ≥ 80%, 误报 < 15%, 延迟 < 2分钟 ?
├── 执行质量: 下单成功率 > 95%, 条件单触发 > 99% ?
├── 风控有效: 熔断触发 < 3秒, 日亏损 < 10% ?
├── 盈亏归因: 盈亏误差 < 0.1%, 与链上一致 ?
├── 监控覆盖: P0 告警 < 30秒, 覆盖率 100% ?
├── 安全合规: 私钥权限 600, 无泄露, 审计完整 ?
└── 模拟验证: 模拟 vs 真实 Pearson > 0.9 ?

    全部通过 → Go → 全量运行
    任一失败 → No-Go → 回退到上一暴露级别
```

---

## 5. 数据流与接口定义

### 5.1 整体数据流

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              数据流图                                    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  [GMGN WebSocket] ──► [GmGnAPI] ──► [数据清洗] ──► [SQLite/JSONL]      │
│       │                     │                                                  │
│       │                     ▼                                                  │
│       │              [钱包候选池] ──► [评分引擎] ──► [白名单]            │
│       │                     │                                                  │
│       │                     ▼                                                  │
│       │              [回测引擎] ──► [策略参数] ──► [Go/No-Go]             │
│       │                                                                        │
│       ▼                                                                        │
│  [gmgn-cli] ──► [信号接入] ──► [预处理] ──► [决策引擎] ──► [执行器]      │
│       │                                                                        │
│       ▼                                                                        │
│  [链上RPC] ──► [持仓同步] ──► [风控监控] ──► [告警/日志] ──► [Loop]      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 5.2 核心接口

```python
# 接口 1: 钱包评分服务
class WalletScoringService:
    def score_wallet(self, address: str) -> WalletScore:
        """对单个钱包进行六维评分"""
        
    def batch_score(self, addresses: list[str]) -> list[WalletScore]:
        """批量评分，支持并行"""
        
    def get_whitelist(self, min_score: float = 70) -> list[WalletScore]:
        """获取白名单（评分 ≥ 阈值）"""

# 接口 2: 回测引擎
class BacktestEngine:
    def run_backtest(
        self,
        wallet_address: str,
        strategy: TradeStrategy,
        period_days: int = 90,
        fee_model: FeeModel = DEFAULT
    ) -> BacktestResult:
        """对指定钱包运行历史回测"""
        
    def compare_strategies(
        self,
        wallet_address: str,
        strategies: list[TradeStrategy]
    ) -> list[BacktestResult]:
        """对比多种策略的表现"""

# 接口 3: 信号监听服务
class SignalMonitor:
    def start_monitoring(self, wallets: list[str]):
        """启动对目标钱包的实时监控"""
        
    def on_trade_event(self, event: TradeEvent) -> TradeSignal:
        """交易事件回调，生成信号"""
        
    def get_pending_signals(self) -> list[TradeSignal]:
        """获取待处理信号队列"""

# 接口 4: 交易执行器
class TradeExecutor:
    def execute(self, signal: TradeSignal) -> TradeExecution:
        """执行交易信号"""
        
    def attach_tp_sl(self, execution: TradeExecution, orders: ConditionOrders):
        """附加止盈止损条件单"""
        
    def emergency_stop(self):
        """紧急停止所有交易"""

# 接口 5: 风控服务
class RiskControlService:
    def check_trade_allowed(self, signal: TradeSignal) -> RiskDecision:
        """检查交易是否允许"""
        
    def check_daily_limit(self) -> bool:
        """检查日亏损是否超限"""
        
    def trigger_circuit_breaker(self, reason: str):
        """触发熔断"""
        
    def get_risk_status(self) -> RiskStatus:
        """获取当前风控状态"""
```

---

## 6. 实施路线图与里程碑

### 6.1 总体时间线

```
Week 1-2:   ████████ 阶段1-A (钱包发现 + 数据管道)
Week 3-4:   ████████ 阶段1-B (评分引擎 + 质量筛选)
Week 5-6:   ████████ 阶段1-C (模拟回测 + 验证调优)
Week 6:     ▓▓▓▓▓▓▓▓ 阶段1 Go/No-Go 决策
Week 7-8:   ████████ 阶段2-A (API接入 + 信号引擎)
Week 9-10:  ████████ 阶段2-B (自动执行 + 风控)
Week 11-12: ████████ 阶段2-C (监控 + 模拟验证)
Week 12:    ▓▓▓▓▓▓▓▓ 阶段2 Go/No-Go 决策
Week 13+:   ████████ 全量运行 + 持续优化 (Loop Engineering)
```

### 6.2 里程碑定义

| 里程碑 | 时间 | 交付物 | 验收标准 |
|--------|------|--------|----------|
| **M1** | Week 2 | 数据管道 + 候选池 | 日抓取 ≥ 5,000，成功率 ≥ 95% |
| **M2** | Week 4 | 评分引擎 + 过滤规则 | 6维评分，人工一致 ≥ 75% |
| **M3** | Week 6 | 回测报告 + 白名单 | 夏普 ≥ 0.5，回撤 ≤ 40%，50+ 合格钱包 |
| **M4** | Week 6 | 阶段1 Go/No-Go | 全部检查通过 |
| **M5** | Week 8 | 信号引擎 + 数据管道 | P95 延迟 < 3秒，准确率 ≥ 80% |
| **M6** | Week 10 | 自动执行 + 风控 | 下单成功率 > 95%，熔断 < 3秒 |
| **M7** | Week 12 | 模拟验证 + 监控 | 模拟 vs 真实 Pearson > 0.9 |
| **M8** | Week 12 | 阶段2 Go/No-Go | 全部检查通过 |
| **M9** | Week 13+ | 全量运行 | 持续优化，Loop 闭合 |

### 6.3 风险与应对

| 风险 | 概率 | 影响 | 应对策略 |
|------|:---:|:---:|:---|
| GMGN API 限流/封禁 | 中 | 高 | 双源冗余（gmgn-cli + Helius），降级到手动模式 |
| 回测过拟合 | 高 | 高 | Walk-Forward 验证，训练/测试集分离，A/B测试 |
| 私钥泄露 | 低 | 极高 | 权限600，环境变量注入，硬件钱包，定期轮换 |
| 市场黑天鹅 | 低 | 高 | 全局熔断，Kill Switch，日/周亏损上限 |
| 开发延期 | 中 | 中 | 模块化设计，每个子目标可独立交付，MVP优先 |
| 策略失效 | 中 | 高 | Loop Engineering 持续监控，权重自优化，A/B测试 |

---

## 7. 附录

### 附录 A：详细设计文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 阶段1-钱包发现与数据收集 | `spec/阶段1-钱包发现与数据收集.md` | 数据管道、候选池、抓取基础设施 |
| 阶段1-评分体系与质量筛选 | `spec/阶段1-评分体系与质量筛选.md` | 6维评分、过滤规则、机器人检测 |
| 阶段1-模拟跟单与回测引擎 | `spec/阶段1-模拟跟单与回测引擎.md` | 回测策略、Walk-Forward、费用模型 |
| 阶段2-API接入与数据管道 | `spec/阶段2-API接入与数据管道.md` | 信号引擎、数据模型、过滤规则 |
| 阶段2-自动化跟单执行引擎 | `spec/阶段2-自动化跟单执行引擎.md` | 执行器、订单管理、CSS决策模型 |
| 阶段2-风控系统与资金管理 | `spec/阶段2-风控系统与资金管理.md` | 风控、熔断、资金管理、渐进暴露 |

### 附录 B：关键术语表

| 术语 | 定义 |
|------|------|
| **Loop Engineering** | 自修复反馈循环工程，5个闭环持续监控和自动修正 |
| **Go/No-Go** | 阶段决策点，全部验收通过则进入下一阶段，否则回退 |
| **CSS** | Comprehensive Signal Score，综合信号评分模型 |
| **Walk-Forward** | 前向回测方法，避免过拟合 |
| **Golden Dog** | 金狗，指涨幅 10 倍以上的优质代币 |
| **Paper Trading** | 模拟交易，不投入真实资金 |
| **Kill Switch** | 紧急停止开关，一键暂停所有交易 |
| **MEV** | 最大可提取价值，三明治攻击等 |
| **Fixed Buy** | 固定金额买入模式 |
| **Max Buy** | 最大金额买入模式 |
| **Fixed Ratio** | 固定比例镜像买入模式 |

### 附录 C：快速启动检查清单

```
□ 安装 Python 3.11+ 和 Node.js 18+
□ 安装依赖: pip install gmgnapi pandas numpy scipy pydantic
□ 安装 gmgn-cli: npm install -g @gmgn/gmgn-cli
□ 配置 API Key: export GMGN_API_KEY=xxx
□ 生成 Ed25519 密钥: openssl genpkey -algorithm ed25519 -out ~/.config/gmgn/private.pem
□ 配置 .env: chmod 600 ~/.config/gmgn/.env
□ 初始化数据库: python3 -m gmgn_monitor.init_db
□ 运行数据抓取: python3 -m gmgn_monitor.fetch --batch-size 1000
□ 运行评分引擎: python3 -m gmgn_monitor.score --input data/wallets.jsonl
□ 运行回测: python3 -m gmgn_monitor.backtest --wallet <address>
□ 启动监控: python3 -m gmgn_monitor.monitor --whitelist data/whitelist.json
□ 验证 Loop: tail -f logs/loop/*.log
```

### 附录 D：参考资源

- [GMGN Skills GitHub](https://github.com/GMGNAI/gmgn-skills)
- [GmGnAPI (Python)](https://github.com/ChipaDevTeam/GmGnAPI)
- [evm-grid-bot](https://pkg.go.dev/github.com/fachebot/evm-grid-bot)
- [GMGN 完整教程](https://grenade.tw/blog/gmgn-ai-tutorial/)
- [Shutdafudup 跟单指南](https://shutdafudup.com/gmgn-copy-trade-settings-and-strategy/)
- [CoinCodeCap Bot 设置](https://coincodecap.com/best-settings-for-gmgn-bot)

---

> **文档维护**: 本 SPEC 为活文档，随着 Loop Engineering 反馈持续更新。任何变更必须通过版本控制和变更审计。

