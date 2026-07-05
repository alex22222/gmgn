# GMGN Monitor — 现有项目探索报告

> 生成时间：基于当前代码库快照（`main` 分支，最新提交 `52995e8`）

---

## 1. 项目目录树结构

```
/Users/henry/projects/gmgn/
├── gmgn_monitor/              # 核心 Python 包（25 个模块）
│   ├── __init__.py
│   ├── analysis.py
│   ├── automation_gate.py
│   ├── config.py
│   ├── dashboard.py
│   ├── dexscreener.py
│   ├── doctor.py
│   ├── execution_eval.py
│   ├── file_io.py
│   ├── fingerprints.py
│   ├── history.py
│   ├── outcomes.py
│   ├── pipeline.py
│   ├── replay.py
│   ├── report.py
│   ├── sample_data.py
│   ├── schema.py
│   ├── scoring.py
│   ├── serialization.py
│   ├── sources.py
│   ├── status.py
│   ├── telegram_dry_run.py
│   ├── time_utils.py
│   ├── trade_plan.py
│   ├── verification_expectations.py
│   ├── verification_report.py
│   └── verification_steps.py
│   └── verify.py
├── tests/                     # 单元测试（22 个测试文件）
│   ├── test_analysis.py
│   ├── test_automation_gate.py
│   ├── test_config.py
│   ├── test_dashboard.py
│   ├── test_dexscreener.py
│   ├── test_doctor.py
│   ├── test_execution_eval.py
│   ├── test_file_io.py
│   ├── test_history.py
│   ├── test_outcomes.py
│   ├── test_pipeline.py
│   ├── test_replay.py
│   ├── test_report.py
│   ├── test_sample_data.py
│   ├── test_scoring.py
│   ├── test_sources.py
│   ├── test_status.py
│   ├── test_telegram_dry_run.py
│   ├── test_trade_plan.py
│   └── test_verify.py
├── config/                    # JSON 配置（5 个文件）
│   ├── automation_gate.json
│   ├── execution_venues.json
│   ├── risk_limits.json
│   ├── thresholds.json
│   └── verification_expectations.json
├── fixtures/                  # 测试/样本数据（JSONL + JSON）
│   ├── candidates.jsonl
│   ├── chain_threshold_candidates.jsonl
│   ├── dexscreener_search_sample.json
│   ├── large_sample_candidates.jsonl
│   ├── malformed_candidate.jsonl
│   ├── missing_field_candidate.jsonl
│   └── outcome_reviews.jsonl
├── data/                      # 生成的输出（pipeline、事件、报告）
│   ├── pipeline/
│   └── *.jsonl / *.md / *.json / *.txt
├── spec/                      # 中文阶段规格文档（5 份）
├── research/                  # 前期研究报告（20+ 份 Markdown）
├── gmgn_system_spec.md        # 系统规范（Phase 1-5）
├── SCHEMA.md                  # 数据模式定义
├── OPERATIONS.md              # 操作手册
├── README.md
├── pyproject.toml             # 项目元数据（Python ≥3.10）
└── ...（其他审计/文档文件）
```

---

## 2. 关键模块简要说明

### 2.1 数据与 Schema
| 模块 | 说明 |
|------|------|
| `schema.py` | 定义 `Candidate` 冻结数据类，包含 22 个必填字段的严格验证（类型、范围、非空、ISO 时间戳）。 |
| `serialization.py` | 通用 JSON / JSONL 加载器，带行号诊断和 UTF-8 校验。 |
| `time_utils.py` | 仅 `is_iso_timestamp()`，支持 `Z` 后缀。 |
| `sources.py` | `CandidateSource` 协议 + `JsonlCandidateSource` 实现 + `load_events()`。 |

### 2.2 评分与配置
| 模块 | 说明 |
|------|------|
| `scoring.py` | `Thresholds` 数据类 + `score_candidate()`。评分规则：先执行硬拒绝（honeypot、黑名单、权限、集中度等），再通过 8 项条件加分（满分 100），最终决策为 `reject`/`watch`/`alert`。 |
| `config.py` | `ThresholdConfig` 类，支持 `default` + 按 `chains` 覆盖（如 `solana`/`base`/`bsc`）。校验阈值数值范围、字段白名单、`alert_score ≥ watch_score`。 |

### 2.3 数据源与输入
| 模块 | 说明 |
|------|------|
| `dexscreener.py` | 只读 DEX Screener 适配器：支持 `search`、`latest token profiles`、`tokens` 三个端点。将 API 返回的 pair/profile 映射为 `Candidate`。注意：缺少安全字段时全部填入保守的不安全默认值（`honeypot_risk=true` 等），因此默认可通过 schema 验证但会被 reject。 |
| `sample_data.py` | 生成确定性候选样本（200 条），用于大样本回放测试。 |

### 2.4 管道与处理
| 模块 | 说明 |
|------|------|
| `replay.py` | 核心回放引擎：读取 JSONL → 验证 schema → 按链选择阈值 → 评分 → 附加空 `outcome` → 输出 JSONL。支持 `--summary-only`。 |
| `pipeline.py` | 完整 dry-run 流水线：调用 replay、生成 Telegram 文本、应用复盘、生成 Markdown 摘要与复盘分析、生成交易计划、生成自动化安全门报告。 |
| `outcomes.py` | 加载外部复盘 JSONL（价格变化、drawdown、notes），合并到已评分事件中。支持复盘验证（去重、类型检查）。 |
| `report.py` | 从事件生成 Markdown 日报（决策统计、链统计、来源统计、复盘状态、Top 10 alert/watch）。 |
| `analysis.py` | 生成分数桶分布和按决策的复盘均价统计（5m/30m/24h/drawdown）。 |

### 2.5 交易计划与风控
| 模块 | 说明 |
|------|------|
| `trade_plan.py` | 从 `alert`/`watch` 事件生成人工交易计划（`needs_human_confirmation`）。包含止损、止盈阶梯、无效化规则、人工检查清单。支持日亏损限额阻断。 |
| `automation_gate.py` | Phase 5 自动化安全门评估器。检查 10 项条件（正期望、复盘数量、纸面/影子交易、熔断开关、日志、日亏损限额、安全审查、禁止马丁格尔/DCA/无限重试）。默认状态 `blocked`。 |
| `execution_eval.py` | 执行场所评估（GMGN、Axiom、Trojan、DirectRouting），按可靠性、费用、托管风险排序，生成 Markdown 评估报告。 |

### 2.6 验证与状态
| 模块 | 说明 |
|------|------|
| `verify.py` | 完整本地验证链：运行 pipeline → 检查 expectations → 运行 doctor → 运行单元测试 → 安全扫描。生成 JSON 验证报告 + JSONL 历史记录。支持文件锁防止并发。 |
| `status.py` | 只读状态检查：加载验证报告与历史，检查时效性、步骤完整性、指纹一致性、过期锁、临时文件等。可配置多种严格模式。 |
| `doctor.py` | 健康检查：检查必需文件、生成输出、配置有效性、fixture schema、生成事件格式、验证报告/历史完整性、指纹匹配、安全关键词扫描（禁止 `private_key`、`auto-buy`、`sendTransaction` 等）。 |
| `history.py` | 验证历史 JSONL 的加载、摘要、完整性校验（时间戳顺序、未来时间、状态-步骤一致性、operational summary 匹配）。 |
| `fingerprints.py` | 对 config 和 artifact 文件计算 SHA-256，用于检测漂移。 |

### 2.7 工具与基础设施
| 模块 | 说明 |
|------|------|
| `file_io.py` | 原子写（文本/JSON/JSONL）、持久追加、文件锁、临时文件清理、过期锁检测。 |
| `telegram_dry_run.py` | 生成 Telegram 格式的纯文本提醒（仅写入文件，不发送）。 |
| `verification_expectations.py` | 加载 `config/verification_expectations.json`，校验运营摘要预期。 |
| `verification_report.py` / `verification_steps.py` | 验证报告的加载、步骤完整性检查、状态-步骤一致性检查。 |

### 2.8 仪表盘
| 模块 | 说明 |
|------|------|
| `dashboard.py` | 内置 HTTP 服务器（`127.0.0.1:8765+`），提供中文 Web 界面：状态指标、操作按钮、用户流程、数据源健康、输出文件浏览。支持 POST 执行白名单动作（status / verify / pipeline / replay / trade_plan / telegram_dry_run）。禁止并发执行。 |

---

## 3. 已有配置项

### 3.1 `thresholds.json` — 评分阈值
- `default`: `min_liquidity`(100), `min_volume_5m`(600), `min_tx_count_1m`(60), `max_top10_holder_percent`(30), `max_dev_holding_percent`(5), `max_insider_or_rat_percent`(20), `alert_score`(80), `watch_score`(55)
- `chains` 覆盖：`base`（更宽松）、`bsc`（更宽松）、`solana`（与 default 相同）

### 3.2 `risk_limits.json` — 风控限额
- `daily_loss_limit_percent`: 5.0
- `max_single_position_percent`: 2.0
- `default_stop_loss_percent`: -40.0
- `take_profit_steps`: `[{100%: 50%}, {300%: 50%}]`（两阶梯止盈，合计卖出 100%）

### 3.3 `automation_gate.json` — 自动化安全门
- 10 个布尔/数值开关，当前全部处于阻断状态：
  - `positive_expectancy_after_costs`: false
  - `reviewed_candidate_count`: 4（远低于 `minimum_reviewed_candidate_count`: 200）
  - `paper_or_shadow_results_available`: false
  - `kill_switch_configured`: false
  - `security_review_completed`: false
  - `allows_martingale`: false（正确）
  - `allows_dca_into_losers`: false（正确）
  - `allows_unlimited_retries`: false（正确）

### 3.4 `execution_venues.json` — 执行场所评估
- 4 个场所：GMGN（数据和执行）、Axiom（执行终端）、Trojan（执行 Bot）、DirectRouting（未实现）
- 所有非自建场所的可靠性状态均为 `needs_live_measurement`，费用 0.95%-1.0%

### 3.5 `verification_expectations.json` — 验证预期
- 运营摘要预期：期望 `blocked` 状态、4 个候选、`alert=1, reject=2, watch=1`、`pending=2, reviewed=2`
- 用于 doctor 和 verify 的 drift 检测

---

## 4. 数据模型

### 4.1 输入候选（Candidate）
使用 `dataclass(frozen=True)` 封装，字段共 22 个：
- **字符串必填**：`chain`, `token_address`, `symbol`, `detected_at`, `source`
- **数值必填**：`liquidity`, `market_cap`, `volume_1m`, `volume_5m`, `tx_count_1m`, `holder_count`, `top10_holder_percent`, `dev_holding_percent`, `insider_or_rat_percent`, `bundle_buy_percent`
- **布尔安全标志**：`mint_renounced`, `freeze_renounced`, `lp_burned_or_locked`, `honeypot_risk`, `blacklist_risk`, `tax_risk`

验证规则：缺失字段 → 失败；类型错误 → 失败；数值非负、有限；百分比 ≤100；计数为整数；字符串非空；时间戳 ISO 8601。

### 4.2 评分输出（Scored Event）
在 Candidate 基础上追加：
- `score`: int（0-100）
- `decision`: `"reject" | "watch" | "alert"`
- `reasons`: list[str]（按评分规则追加的有序原因）
- `outcome`: dict（复盘字段，默认全部空值）

### 4.3 阈值模型（Thresholds）
`dataclass`：8 个字段，默认值对应 `default` 配置。

### 4.4 交易计划（Trade Plan）
- `status`: `"needs_human_confirmation" | "blocked"`
- `symbol`, `chain`, `token_address`, `decision`, `score`
- `max_position_percent`
- `reason`, `invalidation_rule`
- `exit_plan`: `{stop_loss_percent, take_profit_steps}`
- `manual_checklist`: list[str]

### 4.5 验证报告（Verification Report）
- `status`: `"ok" | "fail"`
- `generated_at`: ISO 时间戳
- `steps`: 5 步（pipeline, expectations, doctor, tests, safety_scan）
- `operational_summary`: 候选计数、决策分布、复盘分布、自动化门状态
- `config_fingerprints` / `artifact_fingerprints`: SHA-256 映射

---

## 5. 测试覆盖

现有 **22 个测试文件**，主要覆盖：

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_scoring.py` | 强候选 alert、弱候选 watch、honeypot reject、缺失字段异常、自定义阈值改变决策 |
| `test_pipeline.py` | 完整 pipeline dry-run 输出目录生成、文件存在性、内容断言（summary/telegram/gate） |
| `test_doctor.py` | 当前工作区通过检查、报告构建、gate 必须 blocked、生成输出 UTF-8/格式/形状校验、配置有效性、指纹匹配、锁/临时文件过期、安全关键词扫描、验证报告/历史完整性（~40 个测试用例，非常详尽） |
| `test_verify.py` | 验证报告构建、步骤一致性、写入/追加历史、文件锁冲突、JSON 输出、operational summary 读取、expectation drift 检测、指纹构建、配置/artifact 读取错误 |
| `test_dexscreener.py` | pair/profile 映射、schema 有效性、安全默认值 reject、最新 profile 的 pair 富化、网络请求 mock、异常处理（JSON/UTF8/格式/限制/查询）、main 函数错误路径 |
| `test_dashboard.py` | 动作命令白名单、端口探测、启动失败、payload 构建（状态/动作/输出/数据源/用户流程）、数据源健康（JSONL/UTF8/读取错误/DEX payload）、输出读取错误、动作超时/解码错误/启动错误/并发拒绝、HTTP handler 端到端测试 |
| `test_config.py` | threshold 配置加载、链覆盖、未知字段、数值校验、alert≥watch |
| `test_trade_plan.py` | 风险限额加载、计划生成、日亏损阻断、止盈阶梯校验 |
| `test_automation_gate.py` | gate 评估、阻断条件、blocker 列表 |
| `test_execution_eval.py` | 场所加载、排序、报告生成 |
| `test_analysis.py` | 分数桶统计、复盘均价计算 |
| `test_report.py` | Markdown 日报构建 |
| `test_replay.py` | 回放输出、summary 打印、空 outcome 附加 |
| `test_outcomes.py` | 复盘加载/验证/合并、去重检测 |
| `test_history.py` | 历史加载、摘要、完整性校验、时间戳校验 |
| `test_status.py` | 状态构建、时效计算、各种严格模式 |
| `test_file_io.py` | 原子写、追加、文件锁、临时文件清理 |
| `test_sources.py` | JSONL 加载 |
| `test_telegram_dry_run.py` | 消息格式、过滤 reject |
| `test_sample_data.py` | 样本生成确定性、覆盖不同 profile |
| `test_file_io.py` | 同上 |

**测试运行方式**：`python3 -m unittest discover -s tests`

---

## 6. 关键发现：已实现 vs 缺失

### 6.1 ✅ 已实现的功能

1. **Phase 1 — 监控与数据管道（完整）**
   - 候选输入 schema 定义与严格验证（22 字段）
   - 基于 JSONL 的 fixture 数据源和本地回放
   - DEX Screener 只读 API 适配（search + latest profiles）
   - 保守的安全默认值策略（未知 = 不安全）
   - 评分系统：硬拒绝 + 加权加分 → reject/watch/alert
   - 可配置阈值（default + 按链覆盖）
   - 事件输出（JSONL）与 Markdown 日报/复盘分析

2. **Phase 2 — 评分与复盘（已实现）**
   - 200 条大样本生成与回放
   - 复盘记录加载与合并（价格变化、drawdown、notes）
   - 分数桶分布与复盘均价统计

3. **Phase 3 — 人工确认半自动化（已实现）**
   - 交易计划生成（含止损、止盈阶梯、无效化规则、检查清单）
   - 日亏损限额阻断
   - 风险限额配置校验

4. **Phase 4 — 执行层评估（已实现）**
   - 执行场所静态评估（费用、延迟、托管风险、可靠性）
   - 排序与 Markdown 报告生成

5. **Phase 5 — 自动化安全门（已实现）**
   - 10 项条件检查，默认 `blocked`
   - 安全关键词扫描（禁止私钥、签名、自动买卖等）

6. **验证与闭环工程（非常成熟）**
   - 完整验证链：pipeline → expectations → doctor → tests → safety_scan
   - 验证报告 + JSONL 历史记录
   - 文件锁防并发、原子写、临时文件清理
   - 配置/产物指纹漂移检测
   - 健康检查（doctor）：40+ 细粒度检查
   - 状态监控（status）：支持时效、历史、锁、临时文件多维检查
   - 中文 Web 仪表盘（本地 HTTP）：操作按钮、流程指引、数据源健康、输出浏览

7. **安全边界（严格执行）**
   - 代码库中**无**钱包签名、私钥、自动买卖、订单提交、Telegram 网络发送
   - 所有输出均为本地文件（dry-run）

### 6.2 ❌ 缺失或待实现的功能

1. **真实安全数据增强**
   - DEX Screener 仅提供市场数据（liquidity、FDV、volume、tx count），**缺少** holder concentration、dev holding、insider/bundle、mint/freeze、LP、honeypot、blacklist、tax 等安全字段。
   - 当前映射全部使用保守默认值（`honeypot_risk=true` 等），导致 DEX Screener 源几乎不可能产生 `alert`。
   - **需要**：接入安全增强 API（如 GMGN 安全检测、BullX、Rugcheck 等）来补全安全字段。

2. **GMGN 原生数据接入**
   - 尚未接入 GMGN 的“新币发现”或“钱包追踪”真实数据流。
   - 当前主数据源仍是本地 fixture 和 DEX Screener。

3. **实时/流式数据管道**
   - 当前为**离线/批处理**模式：运行命令 → 读取 JSONL → 输出结果。
   - 无 WebSocket、无轮询调度器、无实时流处理。
   - 无 SQLite/数据库持久化，仅 JSONL 文件。

4. **价格追踪与复盘自动化**
   - 复盘数据（`price_change_5m/30m/24h`、`max_drawdown`）需要**手动**填写到 JSONL 中。
   - 无自动价格抓取、无自动复盘回填。

5. **Telegram 真正发送**
   - 当前仅生成文本文件（`telegram_dry_run.txt`），不发送消息。
   - 需要 Bot Token 和网络发送模块才能改为真正提醒。

6. **交易执行层（有意未实现）**
   - 无钱包连接、无签名、无交易广播、无滑点/优先费计算。
   - 这是设计意图：Phase 5 安全门保持 `blocked` 直到证据充分。

7. **回测引擎（仅雏形）**
   - 有 fixture 回放和分数统计，但**无**基于历史时间序列的完整回测（如按分钟/小时模拟持仓、计算 PnL、夏普比率、最大回撤）。
   - `analysis.py` 仅做简单复盘均价，不做完整策略回测。

8. **钱包发现与 KOL 监控**
   - 系统规范提到“Smart wallet or KOL wallet monitoring”，但当前代码中**无**钱包地址追踪、盈亏排名、跟单目标筛选功能。

9. **调度与自动化运行**
   - 无 cron/定时任务、无守护进程、无云函数部署配置。
   - 所有操作需手动运行命令或点击 dashboard 按钮。

10. **数据库存储**
    - 无 SQLite/PostgreSQL 等结构化存储，仅依赖 JSONL 文件。
    - 在候选量增大后，文件 I/O 和查询效率会成为瓶颈。

---

## 7. 总结评估

本项目是一个**设计精良、安全优先、验证驱动**的监控情报系统。代码结构清晰，模块职责单一，测试覆盖全面（尤其对 doctor、verify、dexscreener 和 dashboard 的异常路径测试非常细致）。安全边界严格执行：没有任何交易执行代码，自动化门默认阻断，所有输出都是本地 dry-run 文件。

**当前成熟度**：Phase 1-2 的核心管道和评分系统已就绪，Phase 3-4 的辅助工具已就绪，但系统仍处于**监控/评估阶段**，离真正可产生可交易信号还差：
- 安全数据增强 API 的接入
- 实时数据流/调度器
- 自动价格追踪与复盘回填
- 回测引擎的完善

**下一步建议优先级**：
1. 接入安全增强数据源（补全 holder/dev/LP/honeypot 等字段）
2. 实现轻量轮询调度器（或 cron 包装）让系统可持续运行
3. 接入 GMGN 新币/钱包发现接口
4. 增加 SQLite 持久化层，支持高效查询和统计
5. 实现自动价格追踪与复盘回填
