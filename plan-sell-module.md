# 自动卖出模块设计文档

## 设计目标
为 GMGN 跟单系统补充完整的自动卖出能力，支持：
1. 持仓价格持续监控与更新
2. TP/SL 触发检测（阶梯止盈 + 止损）
3. 跟单卖出信号处理（EXIT/REDUCE）
4. 安全的链上卖出交易执行

## 架构概览

新增 4 个核心模块，1 个集成修改：

```
gmgn_monitor/
├── sell_executor.py        # 卖出执行器（核心：调用 GMGN swap 卖出）
├── sell_trigger.py         # TP/SL 触发引擎（检测价格触发条件）
├── position_monitor.py     # 持仓价格监控（获取实时价格更新 Portfolio）
├── copy_sell_handler.py    # 跟单卖出信号处理（将 EXIT/REDUCE 信号转为卖出）
├── execution_loop.py       # 修改：在买入循环中增加卖出检测逻辑
```

## 接口契约

### 1. SellSignal（卖出信号）

```python
@dataclass(frozen=True)
class SellSignal:
    signal_id: str
    token_address: str          # 要卖出的代币地址
    sell_percent: float       # 卖出比例（100=全卖，50=卖一半）
    trigger_type: Literal["TP", "SL", "COPY_EXIT", "MANUAL"]
    trigger_price_usd: float | None  # 触发价格（可选）
    reason: str               # 触发原因描述
```

### 2. SellExecutor（卖出执行器）

- 封装 GMGN API 的 swap 卖出（input_token=代币, output_token=SOL）
- 通过 `get_wallet_holdings` 获取代币实际余额
- 更新 PortfolioTracker（close_position）和 OrderManager
- 需要与 RealTradeExecutor 相同的安全确认机制

### 3. PositionMonitor（持仓监控）

- 使用现有 `birdeye_client.py` / `dexscreener.py` / `helius_client.py` 获取价格
- 调用 `PortfolioTracker.update_price(token_address, price)`
- 支持定时轮询（cron/循环）

### 4. SellTrigger（触发检测）

- 输入：持仓 + 对应原始信号（含 tp_orders / sl_order）
- 计算价格变动百分比：`(current_price - entry_price) / entry_price * 100`
- 匹配 TP/SL 触发条件，返回 SellSignal
- 支持阶梯止盈（已触发过的 TP 等级需记录，避免重复）

### 5. CopySellHandler（跟单卖出）

- 输入：`TradeSignal(signal_type="EXIT" or "REDUCE")`
- 调用 SellExecutor 执行卖出
- 处理信号优先级（跟单退出 > 手动退出）

## 卖出交易参数（GMGN swap）

```python
swap_params = {
    "chain": "sol",
    "from_address": wallet_address,
    "input_token": token_address,     # 代币 → 卖
    "output_token": SOL_TOKEN_ADDRESS,  # SOL → 买
    "input_amount": str(token_amount_raw),  # 代币数量（考虑精度）
    "slippage": slippage_percent,
    "auto_slippage": False,
}
```

## 安全机制

1. **卖出确认**：与买入相同，支持 `auto_confirm` 开关（默认 False，需人工确认）
2. **余额验证**：卖出前通过 `get_wallet_holdings` 确认实际余额
3. **滑点控制**：使用信号中的 `max_slippage_percent`
4. **风险检查**：卖出前检查 circuit_breaker / kill_switch
5. **卖出保护**：防止在同一轮中重复卖出同一个代币

## 集成点

### execution_loop.py 修改

在 `run_cycle()` 中，在买入流程之后增加：

```python
# g. 更新持仓价格
position_monitor.update_portfolio_prices(portfolio)

# h. 检测 TP/SL 触发
sell_signals = sell_trigger.scan_all_positions(portfolio, signal_map)

# i. 执行卖出
for sell_signal in sell_signals:
    result = sell_executor.execute_sell(sell_signal)
    ...
```

## 实现顺序

1. `sell_executor.py` - 核心：卖出交易执行
2. `sell_trigger.py` - TP/SL 触发检测
3. `position_monitor.py` - 价格监控
4. `copy_sell_handler.py` - 跟单卖出信号
5. 修改 `execution_loop.py` - 集成

## 注意事项

- USDC 有 6 位小数，大多数 meme 代币有 6-9 位小数，卖出时需要正确处理精度
- `get_wallet_holdings` 返回的是代币实际余额（包含小数精度），需要转换为 raw amount
- 阶梯止盈：第 1 级触发卖出 50% 后，第 2 级在剩余 50% 中再卖出 50%（即总量的 25%）
- 需记录已触发的 TP 等级到持久化存储（JSON/DB），防止重启后重复触发
- 止损通常为 100% 卖出（全部清仓）
