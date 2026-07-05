# 阶段2：API接入与数据管道 — 详细实现规范

> **版本**: v1.0  
> **日期**: 2026-06-13  
> **负责**: 交易引擎架构组  
> **状态**: 设计完成，待评审  

---

## 1. 总体架构概览

阶段2的核心任务是：**从阶段1的聪明钱包清单出发，构建一条实时、可靠、可回测验证的数据管道，最终输出可供阶段3（自动化交易执行）消费的标准化信号流。**

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  阶段1输出      │ -> │  钱包监控引擎   │ -> │  信号解析与评分 │ -> │  回测验证器     │
│  聪明钱包列表   │    │  (链上数据抓取) │    │  (交易意图识别) │    │  (模拟执行)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
                                                                              │
                                                                              v
                                                                       ┌─────────────────┐
                                                                       │  信号输出队列   │
                                                                       │  (阶段3消费)    │
                                                                       └─────────────────┘
```

---

## 2. 具体子目标（SMART原则）

### 子目标 S2-1：建立钱包监控基础设施
| 维度 | 定义 |
|------|------|
| **Specific** | 搭建对 N 个聪明钱包的链上交易活动实时监听管道，捕获其买入/卖出/转账事件 |
| **Measurable** | 监控覆盖率 ≥ 目标钱包列表的 95%；延迟 P99 < 60 秒；丢包率 < 1% |
| **Achievable** | 基于 GMGN WebSocket 和 Helius RPC 双源冗余，满足限速要求 |
| **Relevant** | 直接服务于"发现新买入机会"这一核心价值主张 |
| **Time-bound** | 4 个工作日内完成基础设施搭建和 50 个钱包的灰度测试 |

**详细分解：**
- **S2-1.1**: 完成 GMGN API 白名单申请和 Helius API 密钥配置（1天）
- **S2-1.2**: 实现 WebSocket 连接管理器（自动重连、心跳保活、断线告警）（1天）
- **S2-1.3**: 实现交易事件解析器（区分 buy/sell/transfer，提取 token 地址、金额、价格）（1天）
- **S2-1.4**: 灰度测试：50 个钱包 × 7 天连续监控，输出监控质量日报（1天）

---

### 子目标 S2-2：构建链上数据标准化模型
| 维度 | 定义 |
|------|------|
| **Specific** | 定义统一的数据模型，将原始链上交易转化为标准化的"交易事件"和"钱包画像"结构 |
| **Measurable** | 数据模型字段覆盖 ≥ 100%（参考 3.1 和 3.2 定义）；JSON Schema 通过率 100% |
| **Achievable** | 基于已知的 GMGN 数据结构和 Solana 交易格式推导 |
| **Relevant** | 为后续的信号评分和回测提供一致的数据输入 |
| **Time-bound** | 3 个工作日完成模型设计、Schema 定义和验证器 |

**详细分解：**
- **S2-2.1**: 定义 `TransactionEvent` 数据模型（含所有字段、类型、约束）（0.5天）
- **S2-2.2**: 定义 `WalletProfile` 数据模型（含动态评分字段）（0.5天）
- **S2-2.3**: 定义 `TokenSignal` 数据模型（阶段3 的输入格式）（0.5天）
- **S2-2.4**: 实现 Pydantic 模型和 JSON Schema，编写验证器单测（1.5天）

---

### 子目标 S2-3：实现交易意图识别算法（信号引擎）
| 维度 | 定义 |
|------|------|
| **Specific** | 开发算法将钱包的原始交易流识别为可解释的买入信号（如"新建仓"、"加仓"、"再平衡"） |
| **Measurable** | 信号准确率（与人工标注对比）≥ 80%；误报率 < 15%；信号延迟 < 2 分钟 |
| **Achievable** | 基于规则+统计模型的混合策略，已充分研究聪明钱包行为模式 |
| **Relevant** | 核心转换层：从"钱包在交易"到"这是一个值得跟单的机会" |
| **Time-bound** | 5 个工作日完成算法设计、实现和初步验证 |

**详细分解：**
- **S2-3.1**: 实现买入信号检测器（新 token 首次买入、同 token 加仓、抄底加仓）（2天）
- **S2-3.2**: 实现卖出/止损信号检测器（止盈卖出、止损卖出、清仓）（1.5天）
- **S2-3.3**: 实现信号评分算法（ urgency_score, confidence_score, quality_score ）（1.5天）

---

### 子目标 S2-4：建立模拟回测与验证系统
| 维度 | 定义 |
|------|------|
| **Specific** | 对识别出的买入信号进行历史回测模拟，验证"如果跟单，能赚多少" |
| **Measurable** | 回测覆盖所有信号；可计算夏普比率、最大回撤、胜率、盈亏比；支持参数敏感性分析 |
| **Achievable** | 基于 Jupiter/Birdeye 历史价格数据，结合已知的止盈止损规则 |
| **Relevant** | 在真金白银投入前，用数据证明信号的有效性 |
| **Time-bound** | 7 个工作日完成回测引擎、历史数据获取和首批 100 个信号的验证 |

**详细分解：**
- **S2-4.1**: 实现回测引擎（虚拟持仓跟踪、价格查询、止盈止损执行模拟）（2天）
- **S2-4.2**: 集成历史价格数据源（Jupiter Price API / Birdeye API）（1天）
- **S2-4.3**: 对近 30 天的信号进行全量回测，输出收益报告（2天）
- **S2-4.4**: 实现参数敏感性分析（不同止盈止损阈值下的表现对比）（2天）

---

### 子目标 S2-5：部署 Loop Engineering 反馈循环
| 维度 | 定义 |
|------|------|
| **Specific** | 构建 5 个自动化反馈闭环，确保系统持续自我监控、自我修正、自我优化 |
| **Measurable** | 每个 loop 都有可量化的健康指标、告警阈值和自动修正动作；全系统 MTTR < 5 分钟 |
| **Achievable** | 参考 stockconsult 的 Loop Engineering 经验，复用成熟模式 |
| **Relevant** | 系统长期运行可靠性的唯一保障 |
| **Time-bound** | 与 S2-1 到 S2-4 并行推进，每个 loop 1 个工作日 |

**详细分解（见 4. Loop Engineering 反馈循环）：**
- **S2-5.1**: 数据管道健康监控 Loop（3 天）
- **S2-5.2**: 信号质量反馈 Loop（3 天）
- **S2-5.3**: 回测模型漂移监控 Loop（2 天）
- **S2-5.4**: 钱包评分动态校准 Loop（2 天）
- **S2-5.5**: 前端仪表盘新鲜度 Loop（1 天）

---

## 3. 输入/输出数据模型

### 3.1 输入模型：RawTransactionEvent（原始交易事件）

从 GMGN WebSocket / Helius RPC 抓取的原始数据，经过初步解析后的结构：

```python
class RawTransactionEvent(BaseModel):
    """从链上监听到的原始交易事件"""
    
    # === 核心标识 ===
    signature: str                          # 交易签名（唯一标识）
    wallet_address: str                     # 触发交易的钱包地址（Base58）
    token_address: str                      # 代币合约地址（Mint）
    token_symbol: Optional[str] = None      # 代币符号（如 $BONK，可能延迟获取）
    
    # === 交易方向 ===
    direction: Literal["buy", "sell", "transfer"]  # 交易方向
    
    # === 数量与金额 ===
    token_amount: Decimal                   # 交易的代币数量（原始精度）
    sol_amount: Optional[Decimal] = None    # 等值 SOL 数量（买入/卖出时的 SOL 金额）
    usd_amount: Optional[Decimal] = None    # 等值 USD（实时或历史价格换算）
    
    # === 价格信息 ===
    token_price_sol: Optional[Decimal] = None   # 交易时的单价（SOL/Token）
    token_price_usd: Optional[Decimal] = None   # 交易时的单价（USD/Token）
    market_cap: Optional[Decimal] = None        # 交易时的市值
    
    # === 交易费用 ===
    fee_sol: Decimal                        # 实际支付的交易费用（SOL）
    priority_fee_sol: Optional[Decimal] = None   # 优先费用（Jito/SOL）
    
    # === 时间戳 ===
    block_time: datetime                    # 区块时间（UTC）
    received_at: datetime                   # 本系统收到时间（用于计算延迟）
    
    # === 元数据 ===
    dex_platform: Optional[str] = None     # DEX 平台（Raydium / Orca / Pump.fun）
    is_mev_protected: bool = False          # 是否启用了 MEV 保护
    slip_mode: Optional[Literal["Auto", "Turbo", "Anti-MEV"]] = None  # 滑点模式
    
    # === 原始数据保留（用于调试和审计）===
    raw_logs: Optional[List[str]] = None    # 原始交易日志
    raw_data_hash: str                      # 原始数据的 SHA-256 哈希（用于校验）
    
    class Config:
        json_encoders = {Decimal: str}
```

**字段约束说明：**
- `signature` 必须是有效的 Solana 交易签名（64-88 字节 Base58）
- `wallet_address` 和 `token_address` 必须是有效的 Base58 地址
- `direction` 只能通过链上日志的 Program 事件严格推断，不能猜测
- `token_amount` 必须 > 0（对于转账，取绝对值）
- `block_time` 和 `received_at` 的差值（延迟）会被监控，异常 > 5 分钟触发告警

---

### 3.2 输入模型：WalletProfile（钱包画像）

从阶段1 导入或持续更新的钱包动态画像：

```python
class WalletProfile(BaseModel):
    """聪明钱包的动态画像与评分"""
    
    # === 基础信息 ===
    wallet_address: str                     # 钱包地址（Base58）
    first_seen_at: datetime                 # 首次发现时间
    last_updated_at: datetime               # 最后更新时间
    
    # === 阶段1 筛选指标（静态/准静态）===
    overall_win_rate: Decimal              # 总胜率（%）
    weekly_trade_count: int                # 近7天交易笔数
    avg_hold_duration_hours: Decimal        # 平均持仓时长（小时）
    avg_return_multiplier: Decimal         # 平均回报倍数（x）
    avg_investment_usd: Decimal            # 平均单笔投资金额（USD）
    total_profit_usd: Decimal              # 总利润（USD）
    stablecoin_balance_usd: Decimal        # 稳定币余额（USD）
    is_bot_suspected: bool = False          # 是否疑似机器人（交易频率 > 500/7天）
    
    # === 动态评分（实时更新）===
    quality_score: Decimal = Decimal("0")   # 综合质量分（0-100）
    recency_score: Decimal = Decimal("0")   # 活跃度分（0-100）
    consistency_score: Decimal = Decimal("0")  # 一致性分（0-100）
    risk_score: Decimal = Decimal("0")     # 风险分（0-100，越高越危险）
    
    # === 历史表现（滚动窗口）===
    last_7d_signals: int = 0               # 近7天发出的信号数
    last_7d_successful_signals: int = 0     # 近7天成功信号数（盈利 > 0）
    last_7d_avg_return: Decimal = Decimal("0")   # 近7天平均回报
    last_30d_max_drawdown: Decimal = Decimal("0")  # 近30天最大回撤
    
    # === 元数据 ===
    tags: List[str] = []                   # 标签（如 ["pump-fun-early", "5x-hunter"]）
    source: str = "gmgn_research"         # 数据来源
    
    class Config:
        json_encoders = {Decimal: str}
```

---

### 3.3 输出模型：TokenSignal（代币信号）

信号引擎的输出，供阶段3 交易执行器消费：

```python
class TokenSignal(BaseModel):
    """标准化交易信号 — 阶段3 的输入"""
    
    # === 信号标识 ===
    signal_id: str                          # 唯一信号 ID（UUID v4）
    created_at: datetime                    # 信号生成时间
    
    # === 信号来源 ===
    source_wallet: str                      # 触发钱包地址
    wallet_quality_score: Decimal          # 触发时钱包质量分（快照）
    
    # === 信号内容 ===
    token_address: str                      # 目标代币
    token_symbol: Optional[str] = None     # 代币符号
    signal_type: Literal["new_position", "add_position", "rebalance", "reduce", "exit"]  # 信号类型
    
    # === 价格与市场 ===
    entry_price_usd: Optional[Decimal] = None    # 推荐入场价格（USD）
    current_price_usd: Optional[Decimal] = None    # 当前价格（USD）
    current_market_cap: Optional[Decimal] = None   # 当前市值
    liquidity_usd: Optional[Decimal] = None        # 当前流动性（USD）
    
    # === 信号评分（三维）===
    urgency_score: Decimal                 # 紧急度（0-100，越高越需要立即执行）
    confidence_score: Decimal              # 置信度（0-100，基于钱包历史+当前条件）
    quality_score: Decimal                 # 质量分（综合，0-100）
    
    # === 推荐参数（阶段3 可覆盖）===
    recommended_buy_amount_sol: Optional[Decimal] = None  # 建议买入 SOL 数量
    recommended_buy_mode: Optional[Literal["Max", "Fixed", "Ratio"]] = None  # 建议买入模式
    recommended_slippage: Optional[Decimal] = None       # 建议滑点（%）
    recommended_take_profit: Optional[List[Tuple[Decimal, Decimal]]] = None  #  [(倍数, 卖出比例), ...]
    recommended_stop_loss: Optional[Decimal] = None      # 建议止损（-%, 如 -0.65）
    
    # === 验证状态 ===
    backtest_result: Optional[BacktestResult] = None   # 回测结果（如有）
    status: Literal["pending", "validated", "rejected", "executed", "expired"] = "pending"
    
    # === 审计 ===
    raw_transaction_signature: str         # 原始交易签名（可追溯到源事件）
    generation_latency_ms: int             # 从交易发生到信号生成的延迟（毫秒）
    
    class Config:
        json_encoders = {Decimal: str}


class BacktestResult(BaseModel):
    """回测结果子结构"""
    signal_id: str
    backtested_at: datetime
    
    # 模拟执行参数
    simulated_entry_price: Decimal
    simulated_exit_price: Optional[Decimal] = None
    
    # 结果指标
    pnl_pct: Decimal                       # 盈亏百分比
    pnl_usd: Decimal                       # 盈亏金额（USD）
    hold_duration_hours: Decimal           # 持仓时长
    max_drawdown_pct: Decimal              # 最大回撤
    exit_reason: Optional[Literal["take_profit", "stop_loss", "timeout", "manual"]] = None
    
    # 参数敏感性
    params_sweep: Optional[Dict[str, Decimal]] = None  # 不同参数下的结果
```

---

### 3.4 数据流转换图

```
RawTransactionEvent (链上原始事件)
        │
        v
┌─────────────────┐
│  交易方向解析器  │  <- 判断 buy/sell/transfer
└─────────────────┘
        │
        v
┌─────────────────┐
│  钱包画像注入    │  <- 获取 WalletProfile 质量分
└─────────────────┘
        │
        v
┌─────────────────┐
│  信号检测引擎    │  <- 识别 new_position / add_position / ...
└─────────────────┘
        │
        v
┌─────────────────┐
│  信号评分算法    │  <- 计算 urgency / confidence / quality
└─────────────────┘
        │
        v
┌─────────────────┐
│  回测验证器      │  <- 查询历史价格，模拟执行
└─────────────────┘
        │
        v
TokenSignal (标准化输出)
```

---

## 4. 算法/逻辑设计

### 4.1 钱包质量评分公式（动态更新）

钱包质量分 `quality_score` 是阶段2 的核心过滤指标，它直接决定了"这个钱包的交易是否值得转化为信号"。

#### 4.1.1 综合质量分计算

```python
def calculate_quality_score(profile: WalletProfile) -> Decimal:
    """
    综合质量分 = 加权组合多个子维度
    权重基于阶段1 的研究结论和专家经验
    """
    
    # 各维度分（0-100）
    win_rate_score = min(profile.overall_win_rate, Decimal("100"))  # 胜率直接映射
    
    # 回报分：追求 5x+，但 3x 以上也有价值
    return_score = min(profile.avg_return_multiplier * Decimal("20"), Decimal("100"))
    # 例：5x => 100分，3x => 60分，1x => 20分
    
    # 一致性分：持仓周期不能太短（排除秒冲）
    hold_score = min(profile.avg_hold_duration_hours / Decimal("24") * Decimal("25"), Decimal("100"))
    # 例：24h => 25分，72h => 75分，96h+ => 100分
    
    # 规模分：投资规模在 $500-$10K 范围内得分高
    if profile.avg_investment_usd < 500:
        scale_score = profile.avg_investment_usd / Decimal("500") * Decimal("50")
    elif profile.avg_investment_usd <= 10000:
        scale_score = Decimal("50") + (profile.avg_investment_usd - Decimal("500")) / Decimal("9500") * Decimal("50")
    else:
        scale_score = max(Decimal("100") - (profile.avg_investment_usd - Decimal("10000")) / Decimal("10000") * Decimal("30"), Decimal("0"))
    
    # 利润分：总利润越高越好
    profit_score = min(profile.total_profit_usd / Decimal("100000") * Decimal("100"), Decimal("100"))
    # 例：$100K => 100分，$30K => 30分
    
    # 稳定币分：有稳定币余额说明有持续作战能力
    stablecoin_score = min(profile.stablecoin_balance_usd / Decimal("5000") * Decimal("100"), Decimal("100"))
    
    # 机器人嫌疑扣分：直接归零
    if profile.is_bot_suspected:
        return Decimal("0")
    
    # 综合加权（权重总和 = 1.0）
    quality_score = (
        win_rate_score * Decimal("0.25") +      # 胜率最重要
        return_score * Decimal("0.25") +          # 回报能力
        hold_score * Decimal("0.15") +            # 持仓一致性
        scale_score * Decimal("0.15") +           # 投资规模合理性
        profit_score * Decimal("0.10") +          # 历史利润
        stablecoin_score * Decimal("0.10")        # 持续作战能力
    )
    
    return min(quality_score, Decimal("100")).quantize(Decimal("0.1"))
```

#### 4.1.2 动态衰减机制

钱包质量分不是静态的，需要实时更新以反映最新表现：

```python
def update_wallet_scores(profile: WalletProfile, new_signals: List[TokenSignal]) -> None:
    """
    每发出一个新信号，就更新钱包的动态评分
    """
    for signal in new_signals:
        profile.last_7d_signals += 1
        if signal.backtest_result and signal.backtest_result.pnl_pct > 0:
            profile.last_7d_successful_signals += 1
        
        # 更新近7天平均回报（滚动窗口）
        if signal.backtest_result:
            profile.last_7d_avg_return = (
                profile.last_7d_avg_return * (profile.last_7d_signals - 1) + 
                signal.backtest_result.pnl_pct
            ) / profile.last_7d_signals
    
    # 一致性分：根据近7天信号成功率更新
    if profile.last_7d_signals > 0:
        success_rate = Decimal(profile.last_7d_successful_signals) / Decimal(profile.last_7d_signals)
        profile.consistency_score = success_rate * Decimal("100")
    
    # 风险分：如果最近亏损严重，风险分上升
    if profile.last_30d_max_drawdown < Decimal("-0.5"):  # 回撤超过50%
        profile.risk_score += Decimal("20")
    profile.risk_score = min(profile.risk_score, Decimal("100"))
    
    # 活跃度分：近7天有信号 = 活跃
    profile.recency_score = min(Decimal(profile.last_7d_signals) / Decimal("10") * Decimal("100"), Decimal("100"))
    
    # 重新计算综合质量分
    profile.quality_score = calculate_quality_score(profile)
    profile.last_updated_at = datetime.now(timezone.utc)
```

---

### 4.2 信号检测逻辑（交易意图识别）

#### 4.2.1 新仓位信号（new_position）

**触发条件：** 钱包首次买入某个 token（该钱包过去 7 天内没有该 token 的持仓记录）。

```python
def detect_new_position(
    tx: RawTransactionEvent,
    wallet_history: List[RawTransactionEvent]
) -> Optional[TokenSignal]:
    """
    检测"新建仓"信号
    """
    if tx.direction != "buy":
        return None
    
    # 检查该钱包近7天是否有过该 token 的交易
    recent_token_txs = [
        h for h in wallet_history 
        if h.token_address == tx.token_address 
        and h.block_time > tx.block_time - timedelta(days=7)
    ]
    
    if len(recent_token_txs) > 0:
        return None  # 不是新仓位，是加仓或再平衡
    
    # 获取钱包画像
    profile = get_wallet_profile(tx.wallet_address)
    if profile.quality_score < Decimal("60"):
        return None  # 质量分太低，忽略
    
    # 构建信号
    return TokenSignal(
        signal_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        source_wallet=tx.wallet_address,
        wallet_quality_score=profile.quality_score,
        token_address=tx.token_address,
        token_symbol=tx.token_symbol,
        signal_type="new_position",
        entry_price_usd=tx.token_price_usd,
        current_price_usd=tx.token_price_usd,
        current_market_cap=tx.market_cap,
        urgency_score=calculate_urgency_score(tx, profile),
        confidence_score=calculate_confidence_score(tx, profile, "new_position"),
        quality_score=calculate_signal_quality(tx, profile, "new_position"),
        raw_transaction_signature=tx.signature,
        generation_latency_ms=(datetime.now(timezone.utc) - tx.block_time).total_seconds() * 1000
    )
```

#### 4.2.2 加仓信号（add_position）

**触发条件：** 钱包在已有持仓的基础上，再次买入同一 token，且买入金额 ≥ 上次买入的 50%。

```python
def detect_add_position(
    tx: RawTransactionEvent,
    wallet_history: List[RawTransactionEvent]
) -> Optional[TokenSignal]:
    """
    检测"加仓"信号 — 对已有 token 的追加投资
    """
    if tx.direction != "buy":
        return None
    
    # 获取该钱包该 token 的最近买入记录
    recent_buys = [
        h for h in wallet_history 
        if h.token_address == tx.token_address 
        and h.direction == "buy"
        and h.block_time < tx.block_time  # 之前的买入
    ]
    
    if not recent_buys:
        return None  # 没有历史买入，这是新仓位（应由新仓位检测器处理）
    
    last_buy = max(recent_buys, key=lambda x: x.block_time)
    
    # 加仓金额 >= 上次50% 才认为是"有意义"的加仓
    if tx.usd_amount and last_buy.usd_amount:
        if tx.usd_amount < last_buy.usd_amount * Decimal("0.5"):
            return None
    
    profile = get_wallet_profile(tx.wallet_address)
    if profile.quality_score < Decimal("65"):
        return None  # 加仓信号要求更高质量分（因为需要判断趋势）
    
    return TokenSignal(
        signal_type="add_position",
        # ... 其他字段同 new_position，但 urgency_score 更高（因为已有验证）
    )
```

#### 4.2.3 信号评分三维算法

```python
def calculate_urgency_score(tx: RawTransactionEvent, profile: WalletProfile) -> Decimal:
    """
    紧急度：信号需要多快执行
    - 市值越小，越紧急（机会窗口短）
    - 钱包质量越高，越紧急（竞争多）
    - 买入金额越大，越紧急（大资金在动）
    """
    # 市值紧急度（小市值 = 高紧急度，但过小的可能是陷阱）
    if tx.market_cap:
        if tx.market_cap < 100000:  # < $100K
            mc_urgency = Decimal("90")
        elif tx.market_cap < 1000000:  # < $1M
            mc_urgency = Decimal("75")
        elif tx.market_cap < 10000000:  # < $10M
            mc_urgency = Decimal("60")
        else:
            mc_urgency = Decimal("30")
    else:
        mc_urgency = Decimal("50")
    
    # 钱包质量紧急度（高质量钱包的信号，竞争者多，要快）
    wallet_urgency = profile.quality_score
    
    # 买入金额紧急度（大资金 = 更可能是"确定机会"）
    if tx.usd_amount:
        if tx.usd_amount > 5000:
            amount_urgency = Decimal("90")
        elif tx.usd_amount > 1000:
            amount_urgency = Decimal("70")
        else:
            amount_urgency = Decimal("50")
    else:
        amount_urgency = Decimal("50")
    
    urgency = mc_urgency * Decimal("0.4") + wallet_urgency * Decimal("0.3") + amount_urgency * Decimal("0.3")
    return min(urgency, Decimal("100")).quantize(Decimal("0.1"))


def calculate_confidence_score(
    tx: RawTransactionEvent, 
    profile: WalletProfile,
    signal_type: str
) -> Decimal:
    """
    置信度：这个信号"正确"的概率
    - 基于钱包历史胜率
    - 基于该钱包该类型信号的历史成功率
    - 基于 token 的流动性（高流动性 = 更可能是真实机会）
    """
    base_confidence = profile.overall_win_rate  # 钱包总胜率作为基础
    
    # 一致性加成
    consistency_bonus = profile.consistency_score * Decimal("0.2")
    
    # 流动性加成（基于已知数据：流动性高 = 更可信）
    liquidity_bonus = Decimal("0")
    if tx.market_cap:
        if tx.market_cap > 1000000:  # > $1M
            liquidity_bonus = Decimal("10")
    
    # 信号类型调整
    type_adjustment = {
        "new_position": Decimal("0"),     # 新仓位中性
        "add_position": Decimal("5"),    # 加仓有历史验证，+5
        "rebalance": Decimal("0"),
        "reduce": Decimal("-5"),         # 减仓通常不是正面信号
        "exit": Decimal("-10")           # 清仓是负面信号
    }.get(signal_type, Decimal("0"))
    
    confidence = base_confidence + consistency_bonus + liquidity_bonus + type_adjustment
    return min(max(confidence, Decimal("0")), Decimal("100")).quantize(Decimal("0.1"))


def calculate_signal_quality(
    tx: RawTransactionEvent, 
    profile: WalletProfile,
    signal_type: str
) -> Decimal:
    """
    质量分：综合 urgency + confidence + 风险调整
    """
    urgency = calculate_urgency_score(tx, profile)
    confidence = calculate_confidence_score(tx, profile, signal_type)
    
    # 风险调整：钱包风险分高，质量分降低
    risk_adjustment = profile.risk_score * Decimal("-0.3")
    
    quality = (urgency * Decimal("0.4") + confidence * Decimal("0.6")) + risk_adjustment
    return min(max(quality, Decimal("0")), Decimal("100")).quantize(Decimal("0.1"))
```

---

### 4.3 回测策略设计

#### 4.3.1 回测执行逻辑

对每个信号，模拟"如果按推荐参数执行，结果如何"：

```python
def backtest_signal(
    signal: TokenSignal,
    price_data: List[PricePoint],  # 信号发出后的历史价格序列
    config: BacktestConfig
) -> BacktestResult:
    """
    模拟回测单个信号
    """
    entry_price = signal.entry_price_usd or signal.current_price_usd
    if not entry_price:
        raise ValueError("Signal has no entry price")
    
    # 虚拟持仓
    position = {
        "entry_price": entry_price,
        "remaining_pct": Decimal("1.0"),  # 100% 持仓
        "max_price": entry_price,          # 用于追踪止盈
        "min_price": entry_price,          # 用于追踪止损
    }
    
    total_pnl_pct = Decimal("0")
    exit_reason = None
    exit_time = None
    
    for price_point in price_data:
        current_price = price_point.price
        time_elapsed = price_point.timestamp - signal.created_at
        
        # 更新最高/最低价
        position["max_price"] = max(position["max_price"], current_price)
        position["min_price"] = min(position["min_price"], current_price)
        
        # 计算当前价格相对入场价的涨跌幅
        price_change_pct = (current_price - entry_price) / entry_price
        
        # === 止盈逻辑（分批）===
        # 推荐参数：+100% 卖 50%，+300% 卖剩余 50%
        take_profit_levels = signal.recommended_take_profit or [
            (Decimal("2.0"), Decimal("0.5")),   # 2x 卖 50%
            (Decimal("5.0"), Decimal("0.5"))    # 5x 卖剩余 50%（即总持仓的 50%）
        ]
        
        for multiplier, sell_pct in take_profit_levels:
            target_price = entry_price * multiplier
            if current_price >= target_price and position["remaining_pct"] > 0:
                # 执行卖出
                sell_amount = position["remaining_pct"] * sell_pct
                pnl = sell_amount * (current_price - entry_price) / entry_price
                total_pnl_pct += pnl
                position["remaining_pct"] -= sell_amount
                
                if position["remaining_pct"] <= 0:
                    exit_reason = "take_profit"
                    exit_time = price_point.timestamp
                    break
        
        # === 止损逻辑 ===
        stop_loss = signal.recommended_stop_loss or Decimal("-0.65")
        if price_change_pct <= stop_loss and position["remaining_pct"] > 0:
            # 清仓
            pnl = position["remaining_pct"] * price_change_pct
            total_pnl_pct += pnl
            position["remaining_pct"] = Decimal("0")
            exit_reason = "stop_loss"
            exit_time = price_point.timestamp
            break
        
        # === 超时退出（72小时）===
        if time_elapsed > timedelta(hours=72):
            if position["remaining_pct"] > 0:
                pnl = position["remaining_pct"] * price_change_pct
                total_pnl_pct += pnl
                position["remaining_pct"] = Decimal("0")
            exit_reason = "timeout"
            exit_time = price_point.timestamp
            break
    
    # 计算最大回撤
    max_drawdown = Decimal("0")
    peak = entry_price
    for price_point in price_data:
        peak = max(peak, price_point.price)
        drawdown = (price_point.price - peak) / peak
        max_drawdown = min(max_drawdown, drawdown)
    
    return BacktestResult(
        signal_id=signal.signal_id,
        backtested_at=datetime.now(timezone.utc),
        simulated_entry_price=entry_price,
        simulated_exit_price=current_price if exit_reason else None,
        pnl_pct=total_pnl_pct,
        pnl_usd=total_pnl_pct * (signal.recommended_buy_amount_sol or Decimal("0")) * get_sol_price(),
        hold_duration_hours=(exit_time - signal.created_at).total_seconds() / 3600 if exit_time else Decimal("72"),
        max_drawdown_pct=max_drawdown,
        exit_reason=exit_reason
    )
```

#### 4.3.2 参数敏感性分析

```python
def run_parameter_sweep(
    signal: TokenSignal,
    price_data: List[PricePoint]
) -> Dict[str, Decimal]:
    """
    对同一信号，测试不同止盈止损参数下的表现
    """
    configs = [
        BacktestConfig(name="conservative", take_profit=[(Decimal("2"), Decimal("0.5")), (Decimal("3"), Decimal("0.5"))], stop_loss=Decimal("-0.3")),
        BacktestConfig(name="standard", take_profit=[(Decimal("2"), Decimal("0.5")), (Decimal("5"), Decimal("0.5"))], stop_loss=Decimal("-0.65")),
        BacktestConfig(name="aggressive", take_profit=[(Decimal("3"), Decimal("0.3")), (Decimal("5"), Decimal("0.3")), (Decimal("10"), Decimal("0.4"))], stop_loss=Decimal("-0.65")),
    ]
    
    results = {}
    for config in configs:
        result = backtest_signal(signal, price_data, config)
        results[config.name] = result.pnl_pct
    
    return results
```

---

### 4.4 过滤规则体系

信号不是全部放行，需要多层过滤：

```python
class SignalFilter:
    """信号过滤规则引擎"""
    
    @staticmethod
    def apply_all(signal: TokenSignal) -> Tuple[bool, str]:
        """
        应用所有过滤规则，返回 (是否通过, 拒绝原因)
        """
        # 规则1：钱包质量分 >= 60
        if signal.wallet_quality_score < Decimal("60"):
            return False, "wallet_quality_too_low"
        
        # 规则2：信号质量分 >= 50
        if signal.quality_score < Decimal("50"):
            return False, "signal_quality_too_low"
        
        # 规则3：置信度 >= 50
        if signal.confidence_score < Decimal("50"):
            return False, "confidence_too_low"
        
        # 规则4：市值过滤（排除过小或过大）
        if signal.current_market_cap:
            if signal.current_market_cap < 50000:  # < $50K，可能是死盘
                return False, "market_cap_too_low"
            if signal.current_market_cap > 500000000:  # > $500M，大船难翻
                return False, "market_cap_too_high"
        
        # 规则5：流动性过滤（必须已知）
        if not signal.liquidity_usd or signal.liquidity_usd < 10000:  # < $10K 流动性
            return False, "insufficient_liquidity"
        
        # 规则6：已知诈骗 token 黑名单
        if is_blacklisted_token(signal.token_address):
            return False, "blacklisted_token"
        
        # 规则7：时间衰减（信号超过 10 分钟未处理，紧急度降低）
        if signal.urgency_score > Decimal("70"):
            age_minutes = (datetime.now(timezone.utc) - signal.created_at).total_seconds() / 60
            if age_minutes > 10:
                return False, "signal_expired"
        
        # 规则8：同一 token 同钱包 24h 内重复信号去重
        if has_recent_signal(signal.token_address, signal.source_wallet, hours=24):
            return False, "duplicate_signal"
        
        return True, "passed"
```

---

## 5. Loop Engineering 反馈循环

基于 stockconsult 的 Loop Engineering 经验，阶段2 部署 5 个核心反馈循环：

### 5.1 Loop 1：数据管道健康监控（Pipeline Health Loop）

**目标：** 确保数据管道不中断、不丢包、不延迟。

```python
class PipelineHealthLoop:
    """Loop 1：数据管道健康监控"""
    
    CHECK_INTERVAL_SECONDS = 60
    
    def check(self) -> LoopStatus:
        metrics = {
            "ws_connected": self.ws_client.is_connected(),
            "messages_per_minute": self.ws_client.message_rate_1min(),
            "avg_latency_ms": self.ws_client.avg_latency_ms(),
            "p99_latency_ms": self.ws_client.p99_latency_ms(),
            "parse_error_rate": self.parser.error_rate_1min(),
            "queue_depth": self.signal_queue.qsize(),
        }
        
        # 健康检查
        alerts = []
        if not metrics["ws_connected"]:
            alerts.append("CRITICAL: WebSocket disconnected")
            self.auto_reconnect()  # 自动修正：重连
        
        if metrics["messages_per_minute"] < 5:  # 正常应 > 5 条/分钟（50个钱包）
            alerts.append("WARNING: Message rate too low")
        
        if metrics["p99_latency_ms"] > 60000:  # 60 秒
            alerts.append("WARNING: High latency")
        
        if metrics["parse_error_rate"] > 0.05:  # 5%
            alerts.append("WARNING: High parse error rate")
            self.auto_rebuild_parser()  # 自动修正：重载解析器
        
        if metrics["queue_depth"] > 1000:
            alerts.append("WARNING: Queue backlog")
            self.auto_scale_workers()  # 自动修正：增加消费者线程
        
        # 推送飞书/日志
        if alerts:
            self.send_alert(alerts)
        
        # 保存到 SQLite 时序表
        self.log_metrics(metrics)
        
        return LoopStatus(ok=len(alerts) == 0, alerts=alerts)
```

**验收指标：**
- MTTR（平均修复时间）< 5 分钟
- 数据丢失率 < 1%
- P99 延迟 < 60 秒

---

### 5.2 Loop 2：信号质量反馈（Signal Quality Feedback Loop）

**目标：** 信号发出后，持续追踪其表现，反馈修正信号生成算法。

```python
class SignalQualityLoop:
    """Loop 2：信号质量反馈"""
    
    CHECK_INTERVAL_HOURS = 24
    
    def evaluate(self, window_hours: int = 24) -> LoopStatus:
        """
        评估过去 24 小时发出的信号质量
        """
        signals = self.get_signals_since(hours=window_hours)
        
        # 对有 backtest_result 的信号进行统计
        evaluated = [s for s in signals if s.backtest_result]
        if not evaluated:
            return LoopStatus(ok=True, alerts=["No evaluated signals yet"])
        
        win_signals = [s for s in evaluated if s.backtest_result.pnl_pct > 0]
        loss_signals = [s for s in evaluated if s.backtest_result.pnl_pct <= 0]
        
        metrics = {
            "total_signals": len(signals),
            "evaluated_signals": len(evaluated),
            "win_rate": len(win_signals) / len(evaluated) * 100 if evaluated else 0,
            "avg_pnl_pct": sum(s.backtest_result.pnl_pct for s in evaluated) / len(evaluated) if evaluated else 0,
            "avg_win_pnl": sum(s.backtest_result.pnl_pct for s in win_signals) / len(win_signals) if win_signals else 0,
            "avg_loss_pnl": sum(s.backtest_result.pnl_pct for s in loss_signals) / len(loss_signals) if loss_signals else 0,
        }
        
        alerts = []
        
        # 如果胜率低于 50%，需要调整过滤阈值
        if metrics["win_rate"] < 50:
            alerts.append(f"WARNING: Win rate dropped to {metrics['win_rate']:.1f}%, adjusting quality_score threshold")
            self.auto_adjust_thresholds(direction="tighten")  # 收紧过滤
        
        # 如果平均亏损过大，收紧止损参数
        if metrics["avg_loss_pnl"] < -0.5:  # 平均亏损 > 50%
            alerts.append(f"WARNING: Avg loss {metrics['avg_loss_pnl']:.1%}, tightening stop_loss")
            self.auto_adjust_stop_loss(direction="tighten")
        
        # 如果平均盈利过低，放宽止盈或调整参数
        if metrics["avg_win_pnl"] < 0.5:  # 平均盈利 < 50%
            alerts.append(f"WARNING: Avg win {metrics['avg_win_pnl']:.1%}, reviewing take_profit levels")
        
        self.log_metrics(metrics)
        self.send_daily_report(metrics)
        
        return LoopStatus(ok=len(alerts) == 0, alerts=alerts, metrics=metrics)
```

**验收指标：**
- 信号胜率追踪准确率 100%（所有信号都有 backtest_result）
- 参数自动调整响应时间 < 24 小时
- 信号质量分与回测 PnL 的相关系数 > 0.6

---

### 5.3 Loop 3：回测模型漂移监控（Backtest Drift Loop）

**目标：** 回测结果与实际执行（阶段3）的偏差监控。

```python
class BacktestDriftLoop:
    """Loop 3：回测 vs 实际执行偏差监控"""
    
    def compare(self, executed_signals: List[ExecutedSignal]) -> LoopStatus:
        """
        对比回测预测和实际执行结果
        """
        deviations = []
        for exec_sig in executed_signals:
            if not exec_sig.backtest_result:
                continue
            
            predicted_pnl = exec_sig.backtest_result.pnl_pct
            actual_pnl = exec_sig.actual_pnl_pct
            
            deviation = abs(actual_pnl - predicted_pnl)
            deviations.append(deviation)
        
        if not deviations:
            return LoopStatus(ok=True)
        
        avg_deviation = sum(deviations) / len(deviations)
        max_deviation = max(deviations)
        
        alerts = []
        if avg_deviation > Decimal("0.15"):  # 平均偏差 > 15%
            alerts.append(f"WARNING: Avg backtest drift {avg_deviation:.1%}, recalibrating price model")
            self.auto_recalibrate_price_source()  # 修正：切换价格数据源或修正滑点模型
        
        if max_deviation > Decimal("0.5"):  # 最大偏差 > 50%
            alerts.append(f"CRITICAL: Max backtest drift {max_deviation:.1%}, investigating outliers")
            self.auto_investigate_outliers()  # 修正：标记异常信号，人工审查
        
        self.log_metrics({"avg_drift": avg_deviation, "max_drift": max_deviation})
        
        return LoopStatus(ok=len(alerts) == 0, alerts=alerts)
```

**验收指标：**
- 回测与实际执行的平均偏差 < 10%
- 异常偏差（> 30%）的信号 < 5%
- 价格源切换响应时间 < 1 小时

---

### 5.4 Loop 4：钱包评分动态校准（Wallet Score Calibration Loop）

**目标：** 钱包质量分不是静态的，需要根据其最新信号表现持续更新。

```python
class WalletScoreCalibrationLoop:
    """Loop 4：钱包评分动态校准"""
    
    CALIBRATION_INTERVAL_HOURS = 168  # 每周校准一次
    
    def calibrate(self) -> LoopStatus:
        """
        每周对所有监控钱包的评分进行校准
        """
        wallets = self.get_all_monitored_wallets()
        
        alerts = []
        for wallet in wallets:
            # 重新计算该钱包的质量分
            new_score = calculate_quality_score(wallet)
            old_score = wallet.quality_score
            
            # 如果分数下降超过 20，发出警告
            if old_score - new_score > 20:
                alerts.append(f"WARNING: Wallet {wallet.wallet_address[:8]}... score dropped {old_score:.1f} -> {new_score:.1f}")
            
            # 如果分数低于 50，考虑移除监控
            if new_score < 50:
                alerts.append(f"INFO: Wallet {wallet.wallet_address[:8]}... below threshold, queueing for removal review")
                self.queue_for_removal(wallet)
            
            # 更新分数
            wallet.quality_score = new_score
            self.save_wallet(wallet)
        
        return LoopStatus(ok=len(alerts) == 0, alerts=alerts)
```

**验收指标：**
- 钱包评分更新频率 ≥ 1 次/周
- 评分下降钱包的识别准确率 > 80%
- 低质量钱包的移除响应时间 < 1 周

---

### 5.5 Loop 5：仪表盘新鲜度（Dashboard Freshness Loop）

**目标：** 前端仪表盘数据必须是最新的，过期数据需要明确标注。

```python
class DashboardFreshnessLoop:
    """Loop 5：前端仪表盘数据新鲜度"""
    
    CHECK_INTERVAL_SECONDS = 30
    
    def check(self) -> LoopStatus:
        """
        检查所有前端数据的新鲜度
        """
        metrics = {
            "last_signal_time": self.get_last_signal_time(),
            "last_wallet_update": self.get_last_wallet_update(),
            "last_price_update": self.get_last_price_update(),
            "last_backtest_run": self.get_last_backtest_run(),
        }
        
        now = datetime.now(timezone.utc)
        alerts = []
        
        for metric_name, last_time in metrics.items():
            age_seconds = (now - last_time).total_seconds() if last_time else float('inf')
            
            # 不同指标有不同的新鲜度阈值
            thresholds = {
                "last_signal_time": 300,      # 5 分钟
                "last_wallet_update": 3600,  # 1 小时
                "last_price_update": 60,     # 1 分钟
                "last_backtest_run": 86400,  # 24 小时
            }
            
            threshold = thresholds.get(metric_name, 300)
            if age_seconds > threshold:
                alerts.append(f"WARNING: {metric_name} stale by {age_seconds:.0f}s")
                self.update_dashboard_badge(metric_name, "stale")  # 修正：前端显示过时标签
        
        self.push_freshness_status(metrics)
        
        return LoopStatus(ok=len(alerts) == 0, alerts=alerts)
```

**验收指标：**
- 数据新鲜度检查频率 ≥ 1 次/30 秒
- 过时数据的前端标注覆盖率 100%
- 所有关键指标都有新鲜度时间戳

---

### 5.6 反馈循环汇总表

| Loop | 名称 | 检查频率 | 核心指标 | 自动修正动作 | 验收标准 |
|------|------|----------|----------|-------------|----------|
| L1 | 管道健康 | 1 分钟 | 连接状态、延迟、丢包率、队列深度 | 自动重连、增worker、重载解析器 | MTTR < 5min, 丢包 < 1% |
| L2 | 信号质量 | 24 小时 | 信号胜率、盈亏比、平均PnL | 自动调整过滤阈值、止盈止损参数 | 响应 < 24h, 相关系数 > 0.6 |
| L3 | 回测漂移 | 每笔执行后 | 回测 vs 实际偏差 | 切换价格源、修正滑点模型 | 偏差 < 10%, 异常 < 5% |
| L4 | 钱包校准 | 1 周 | 质量分变化、钱包表现退化 | 标记低分钱包、发起移除审查 | 更新 ≥ 1次/周, 识别准确率 > 80% |
| L5 | 仪表盘新鲜度 | 30 秒 | 各数据源的更新时间 | 前端标注过时、推送告警 | 覆盖率 100%, 标注及时 |

---

## 6. 验收标准

### 6.1 总体验收标准

| 编号 | 验收项 | 验收标准 | 测试方法 |
|------|--------|----------|----------|
| A-01 | 钱包监控覆盖率 | 目标列表中 ≥ 95% 的钱包处于活跃监控状态 | 对比监控列表 vs 目标列表 |
| A-02 | 数据延迟 | P99 延迟 < 60 秒（从交易上链到信号生成） | 日志分析：(created_at - block_time) 的 P99 |
| A-03 | 信号准确率 | 新仓位信号准确率 ≥ 80%（与人工标注对比，抽样 100 条） | 人工标注 100 条信号，对比算法判断 |
| A-04 | 回测完整性 | 所有发出的信号都有 backtest_result，且 72h 内完成 | 查询数据库，统计信号覆盖率和完成时间 |
| A-05 | 回测可靠性 | 回测与实际执行的平均偏差 < 10% | 阶段3 上线后对比 |
| A-06 | 系统可用性 | 数据管道 7×24 连续运行，可用性 ≥ 99% | 监控日志，统计故障时间 |
| A-07 | 告警响应 | 所有 Loop 的告警都在 5 分钟内触达（飞书/日志） | 模拟故障，测试告警链路 |
| A-08 | 数据一致性 | 信号队列中的信号与数据库记录 100% 一致 | 队列消费校验 vs 数据库校验 |

### 6.2 分阶段验收

**S2-1 验收（钱包监控基础设施）：**
- [ ] GMGN API 白名单申请通过，Helius API 密钥配置完成
- [ ] WebSocket 连接管理器通过压力测试（模拟 1000 次断连，自动恢复率 100%）
- [ ] 50 个钱包 × 7 天连续监控，日报显示覆盖率 > 95%，延迟 P99 < 60s
- [ ] 所有监控指标写入 SQLite 时序表，可查询

**S2-2 验收（数据模型）：**
- [ ] Pydantic 模型通过 100% 单测覆盖（字段类型、约束、序列化）
- [ ] JSON Schema 验证器通过 100 条样本数据的验证
- [ ] 三个模型（RawTransactionEvent, WalletProfile, TokenSignal）的转换链路完整

**S2-3 验收（信号引擎）：**
- [ ] 信号检测器通过 100 条人工标注测试（准确率 > 80%）
- [ ] 信号评分算法输出稳定（同一输入，评分差异 < 5%）
- [ ] 信号延迟 < 2 分钟（从交易发生到 signal 生成）

**S2-4 验收（回测系统）：**
- [ ] 回测引擎通过 100 个已知结果信号的验证（PnL 计算误差 < 1%）
- [ ] 参数敏感性分析输出包含至少 3 个参数组合的结果
- [ ] 历史价格数据获取成功率 > 95%（测试 1000 个 token）

**S2-5 验收（反馈循环）：**
- [ ] 5 个 Loop 全部运行，监控面板可查看状态
- [ ] 每个 Loop 的告警都成功触达（飞书/日志）
- [ ] 自动修正动作至少触发一次并正确执行（可通过模拟故障验证）

---

## 7. 失败回退策略

### 7.1 按子目标的回退策略

#### S2-1 失败回退：钱包监控基础设施

| 失败场景 | 回退策略 | 恢复步骤 |
|----------|----------|----------|
| GMGN WebSocket 无法连接 | 切换到 Helius RPC 的日志流（gRPC）作为备用数据源 | 1. 自动重试 GMGN 连接（指数退避，最多 5 次）；2. 切换 Helius 备用；3. 告警通知 |
| Helius API 额度耗尽 | 使用社区 RPC 节点（如 QuickNode）的免费额度 | 1. 检查 Helius 用量；2. 切换 QuickNode；3. 申请 Helius 升级套餐 |
| 钱包数量超过 GMGN 限速 | 钱包分批监控（优先级队列），只监控质量分 Top 50% | 1. 按质量分排序；2. 取 Top N；3. 低质量钱包进入冷监控（5 分钟/次） |
| 交易解析失败率 > 5% | 回退到原始日志保留模式，人工标注修复解析器 | 1. 保留原始日志；2. 人工审查失败案例；3. 更新解析规则；4. 重放验证 |

#### S2-2 失败回退：数据模型

| 失败场景 | 回退策略 | 恢复步骤 |
|----------|----------|----------|
| 模型验证失败（GMGN 数据格式变更） | 回退到宽松的 dict 模式，字段缺失时赋默认值 | 1. 记录失败样本；2. 更新 Pydantic 模型；3. 重新验证；4. 补全历史数据 |
| 数据类型不匹配（如 price 为字符串） | 添加自动类型转换层（str -> Decimal） | 1. 在解析器层添加 sanitize 函数；2. 记录所有类型转换事件；3. 定期审计 |

#### S2-3 失败回退：信号引擎

| 失败场景 | 回退策略 | 恢复步骤 |
|----------|----------|----------|
| 信号准确率 < 70%（验收失败） | 收紧过滤规则（质量分阈值从 60 提高到 75），减少误报 | 1. 分析误报案例；2. 调整过滤规则；3. 重新测试；4. 逐步放宽 |
| 信号延迟 > 2 分钟 | 简化信号计算逻辑（跳过非关键字段），或增加预计算 | 1. 识别延迟瓶颈；2. 简化计算；3. 增加缓存；4. 异步化非关键路径 |
| 信号评分不稳定（同一输入不同结果） | 检查是否有随机性（如时间依赖），移除或固定 | 1. 审计算法；2. 固定所有随机种子；3. 单元测试确保确定性 |

#### S2-4 失败回退：回测系统

| 失败场景 | 回退策略 | 恢复步骤 |
|----------|----------|----------|
| 历史价格数据获取失败 | 使用 GMGN 的实时价格作为近似（误差可能较大，标记为 approximated） | 1. 标记数据质量为 "approximated"；2. 尝试备用数据源；3. 记录缺失数据 |
| 回测 PnL 计算与已知结果偏差 > 5% | 回退到简化回测模型（只计算入场和出场两个价格点） | 1. 对比详细日志；2. 检查中间价格点；3. 简化模型；4. 重测验证 |
| 参数敏感性分析输出异常 | 减少参数组合数量，只测试标准参数 | 1. 检查参数范围；2. 限制组合数；3. 输出基础结果；4. 修复后补充分析 |

#### S2-5 失败回退：反馈循环

| 失败场景 | 回退策略 | 恢复步骤 |
|----------|----------|----------|
| Loop 检查脚本失败 | 回退到手动检查（通过前端仪表盘和日志） | 1. 记录脚本失败原因；2. 修复脚本；3. 手动执行一次完整检查；4. 恢复自动 |
| 自动修正动作执行失败 | 回退到人工告警（飞书通知），由人工介入 | 1. 记录失败动作；2. 发送详细告警；3. 人工执行；4. 修复自动化 |
| 告警通道失败（飞书不可用） | 回退到本地日志 + 邮件告警 | 1. 检查飞书通道；2. 启用邮件备用；3. 本地日志记录所有告警；4. 修复飞书通道 |

### 7.2 全局回退策略

```python
class GlobalFallbackStrategy:
    """
    全局回退：如果阶段2 整体无法按期交付，如何最小化损失
    """
    
    # 方案 A：降级到手动模式
    @staticmethod
    def fallback_to_manual():
        """
        如果自动化管道失败，回退到：
        1. 手动从 GMGN 网站查看聪明钱包交易
        2. 使用 gmgn-cli 手动执行跟单
        3. 用 Excel/Notion 手动跟踪和记录
        """
        pass
    
    # 方案 B：MVP 裁剪
    @staticmethod
    def fallback_to_mvp():
        """
        如果完整阶段2 无法交付，裁剪为 MVP：
        1. 只保留钱包监控（S2-1）和基础信号检测（S2-3 的 new_position 规则）
        2. 回测用 gmgn-cli 的模拟功能代替自建
        3. Loop 只保留 L1（管道健康）和 L5（仪表盘新鲜度）
        4. 输出格式简化为 CSV，不接入阶段3
        """
        pass
    
    # 方案 C：外包/工具替代
    @staticmethod
    def fallback_to_third_party():
        """
        如果自建成本过高，使用：
        1. 使用已有的 gmgn-skills 的 OpenClaw 集成（直接调用而非自建）
        2. 使用 DexScreener / Birdeye 的 API 做钱包追踪
        3. 使用现成的交易机器人框架（如 Solana Trading Bot）
        """
        pass
```

---

## 8. 技术栈建议

### 8.1 Python 核心栈

| 用途 | 库/框架 | 版本 | 说明 |
|------|---------|------|------|
| 数据模型 | `pydantic` | ^2.0 | 所有数据结构的验证和序列化 |
| 数据库 ORM | `sqlalchemy` | ^2.0 | SQLite 主数据库（钱包、信号、回测结果） |
| 时序数据 | `influxdb-client` | ^1.43 | 可选：高频指标存储（延迟、消息速率） |
| 异步网络 | `websockets` | ^12.0 | GMGN WebSocket 客户端 |
| HTTP 请求 | `httpx` | ^0.27 | API 调用（Helius, Jupiter, Birdeye） |
| 任务调度 | `apscheduler` | ^3.10 | Loop 的定时检查任务 |
| 配置管理 | `pydantic-settings` | ^2.0 | 环境变量和 .env 配置 |
| 日志 | `structlog` | ^24.0 | 结构化 JSON 日志 |
| 测试 | `pytest` | ^8.0 | 单元测试 + 集成测试 |
| 类型检查 | `mypy` | ^1.0 | 静态类型检查 |

### 8.2 Node.js / CLI 工具栈

| 用途 | 工具 | 安装 | 说明 |
|------|------|------|------|
| 交易执行 | `gmgn-cli` | `npm install -g gmgn-cli` | GMGN 官方 CLI，支持 6 种订单类型 |
| 智能合约交互 | `solana-cli` | `sh -c "$(curl -sSfL https://release.solana.com/v1.18.2/install)"` | Solana 基础操作 |
| 钱包管理 | `spl-token` | `cargo install spl-token-cli` | SPL Token 操作 |

### 8.3 数据存储

| 用途 | 存储 | 方案 | 说明 |
|------|------|------|------|
| 主数据库 | SQLite | `sqlite3` + `sqlalchemy` | 钱包画像、信号、回测结果（单文件，便于备份） |
| 时序指标 | SQLite 扩展 | `sqlite3` + 时序表设计 | 如用 InfluxDB 则选 `influxdb-client` |
| 缓存 | 内存 | `functools.lru_cache` / `cachetools` | 钱包画像、价格数据缓存 |
| 消息队列 | 内存 | `asyncio.Queue` | 信号流队列（初期） |
| 配置/密钥 | 文件 | `~/.config/gmgn/.env` | 权限 600，私钥绝不入数据库 |

### 8.4 外部 API 和数据源

| 服务 | 用途 | 接入方式 | 限速/成本 |
|------|------|----------|----------|
| GMGN WebSocket | 聪明钱包交易流 | IP 白名单 + WebSocket | 2 次/秒 |
| Helius RPC | 交易日志解析、账户监听 | API Key + gRPC/REST | 免费额度有限，付费套餐 |
| Jupiter Price API | 实时价格、历史价格 | REST API | 免费，限速 |
| Birdeye API | 代币价格、市值、流动性 | REST API | 免费 tier 有限制 |
| DexScreener | 代币对信息、价格 | REST API | 免费 |
| Pump.fun API | Pump.fun 代币毕业状态 | 非官方 / 社区 | 无保证 |

### 8.5 部署和运维

| 用途 | 工具 | 说明 |
|------|------|------|
| 进程管理 | `supervisor` / `systemd` | 守护进程，自动重启 |
| 监控 | `prometheus` + `grafana` | 可选：指标采集和可视化 |
| 告警 | 飞书 webhook | 所有 Loop 的告警通道 |
| 日志收集 | 本地轮转 + 可选 ELK | 结构化日志存储 |
| CI/CD | GitHub Actions | 测试、构建、部署自动化 |

---

## 9. 依赖关系与里程碑

```
Week 1:  S2-1.1 (API白名单) -> S2-1.2 (WebSocket) -> S2-1.3 (解析器) -> S2-1.4 (灰度测试)
            │
            v
Week 2:  S2-2 (数据模型) -> S2-3.1 (买入信号) -> S2-3.2 (卖出信号) -> S2-3.3 (评分算法)
            │                                    │
            v                                    v
Week 3:  S2-4.1 (回测引擎) -> S2-4.2 (价格数据) -> S2-4.3 (全量回测) -> S2-4.4 (参数分析)
            │
            v
Week 4:  S2-5 (5个Loop) -> 集成测试 -> 验收评审
```

**关键路径：** S2-1 -> S2-2 -> S2-3 -> S2-4 -> S2-5

**可并行任务：**
- S2-1（基础设施）和 S2-2（数据模型）可并行
- S2-3（信号引擎）和 S2-5 的 L1/L5（基础 Loop）可并行
- S2-4（回测）和 S2-5 的 L2/L3/L4（高级 Loop）可并行

---

## 10. 风险与应对

| 风险 | 影响 | 可能性 | 应对策略 |
|------|------|--------|----------|
| GMGN API 关闭或变更 | 高 | 中 | 保留 Helius 备用；实现交易日志的通用解析器 |
| 信号准确率长期不达标 | 高 | 中 | 收紧过滤；增加人工审核；定期更换钱包列表 |
| 回测与实际偏差过大 | 高 | 中 | 多数据源交叉验证；保守估计滑点和费用 |
| 目标钱包突然失效 | 中 | 高 | 动态评分自动降级；持续从阶段1 补充新钱包 |
| 数据量过大导致性能问题 | 中 | 中 | SQLite 分表分库；关键数据放内存缓存；定期归档 |
| 私钥泄露 | 极高 | 低 | .env 权限 600；服务器不存储私钥；使用只读钱包做监控 |

---

> **文档结束**  
> 本规范为阶段2 的详细实现指南，所有子目标均按照 SMART 原则设计，可直接分解为任务单并进入开发阶段。  
> 建议在开始开发前，由架构组、交易组、运维组进行评审，确认验收标准和回退策略。
