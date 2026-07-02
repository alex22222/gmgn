## Dimension 06: 自动化与量化策略

### Current State
GMGN 已经构建了一个覆盖完整交易自动化的生态系统，包括官方 CLI 工具（gmgn-cli）、AI Agent Skills（gmgn-skills）、Telegram Bot 自动化交易、多钱包批量交易、以及通过 API 和 WebSocket 的数据获取能力。2026 年趋势显示 AI Agent 正在从规则型交易 bot 向自主决策型 Agent 演进，Solana 因其高吞吐量和低成本成为 AI Agent 交易的主战场。GMGN 官方 Skills 支持 OpenClaw、Claude Code、Cursor、Cline、Codex CLI 等多种 AI 客户端集成，使自然语言驱动的链上交易成为可能。然而，GMGN 核心数据 API 未向公众开放，仅提供 IP 白名单数据抓取（限速 2 次/秒），开发者需借助社区工具（GmGnAPI、gmgnai-scraping）或官方 Skills 进行程序化访问。社区开源工具链已相当成熟，覆盖新池狙击、网格交易、DCA 策略、MEV 防护等多维度。meme 币市场的高波动性（98.6% 的 Pump.fun 代币为 pump-and-dump）使得追踪止盈止损、止损退出和自动化风控成为刚需。

### Key Evidence

**Claim 1: GMGN 官方提供 gmgn-cli 和 gmgn-skills 两个核心工具，支持通过自然语言查询和交易多链 meme 代币**
Source: GMGN Skills GitHub (GMGNAI/gmgn-skills)
URL: https://github.com/GMGNAI/gmgn-skills
Date: 2026-06-12
Excerpt: "With GMGN Agent Skills, you can use AI agents to query real-time trending token rankings across multiple chains... execute on-chain trades across Solana, BSC, and Base."
Context: 这是官方 AI Agent 集成的核心文档，包含6大技能：token、market、portfolio、track、swap、cooking。端到端订单延迟低于 0.3 秒。
Confidence: high

**Claim 2: gmgn-cli 安装通过 npm 完成，配置需要 Ed25519 密钥对和 GMGN API Key**
Source: GMGN Skills Quick Start (AI Agent)
URL: https://github.com/GMGNAI/gmgn-skills/blob/main/Readme.md
Date: 2026-06-12
Excerpt: "Step 1: npx skills add GMGNAI/gmgn-skills; Step 2: GMGN_API_KEY=gmgn_solbscbaseethmonadtron gmgn-cli market trending --chain sol --interval 1h --limit 3; Step 3: openssl genpkey -algorithm ed25519 -out /tmp/gmgn_private.pem"
Context: 安装流程分为 Agent 安装、npm 全局安装和本地开发三种方式。配置要求 API key 和 private key 存储在 ~/.config/gmgn/.env 中，权限设置为 600。
Confidence: high

**Claim 3: gmgn-cli 支持6种订单类型：市价单、限价单、止盈止损策略单、追踪止盈、追踪止损、多钱包批量交易**
Source: GMGN Skills README
URL: https://github.com/GMGNAI/gmgn-skills
Date: 2026-06-12
Excerpt: "Market Order — Instant execution at current market price; Limit Order — Trigger buy or sell at a specified price; Take-Profit / Stop-Loss — Fixed-price exit conditions; Trailing Take-Profit / Trailing Stop-Loss — Tracks price peak; fires after a specified drawdown %; Multi-Wallet Batch Trading — Buy with multiple wallets simultaneously."
Context: 多钱包批量交易支持每个钱包独立设置 TP/SL/追踪止盈/追踪止损。订单提交通过同一 RPC 路由引擎，实现毫秒级响应。
Confidence: high

**Claim 4: gmgn-cli 的 "cooking" 命令支持一键买入并自动附加止盈止损条件单**
Source: GMGN Skills CLI Reference
URL: https://github.com/GMGNAI/gmgn-skills/blob/main/Readme.md
Date: 2026-06-12
Excerpt: "gmgn-cli cooking --chain sol --from <wallet> --input-token So111... --output-token <token> --amount 1000000000 --slippage 30 --condition-orders '[{\"order_type\":\"profit_stop\",\"side\":\"sell\",\"price_scale\":\"100\",\"sell_ratio\":\"100\"},{\"order_type\":\"loss_stop\",\"side\":\"sell\",\"price_scale\":\"50\",\"sell_ratio\":\"100\"}]'"
Context: cooking 命令将买入和条件订单绑定为单一流，适合自动策略。condition-orders 支持 price_scale（涨幅/跌幅百分比）和 sell_ratio（卖出比例）。两种模式：hold_amount（基于当前持仓）和 buy_amount（基于原始买入量）。
Confidence: high

**Claim 5: gmgn-cli 支持多钱包并发 swap（multi-swap），每个钱包可独立设置金额**
Source: GMGN Skills CLI Reference
URL: https://github.com/GMGNAI/gmgn-skills/blob/main/Readme.md
Date: 2026-06-12
Excerpt: "gmgn-cli multi-swap --chain sol --accounts <addr1>,<addr2> --input-token <input> --output-token <output> --input-amount '{\"<addr1>\":\"1000000\",\"<addr2>\":\"2000000\"}' --slippage 30"
Context: multi-swap 命令允许一次调用多个钱包同时交易，适合资金分散策略或测试多个钱包。需要 GMGN_PRIVATE_KEY 进行签名认证。
Confidence: high

**Claim 6: GMGN Telegram Bot 支持最多跟单 10 个地址，可设置固定买入金额、最大跟买、自动跟卖、止盈止损、防夹**
Source: GMGN Copy Trading Tutorial (FollowIn)
URL: https://followin.io/en/feed/14515025
Date: 2026-04
Excerpt: "The GMGN trading bot can follow up to 10 addresses... Set the fixed buy-in and maximum follow-up buy... Enable auto follow-up sell... Users can also set take profit/stop loss and choose not to follow sell... priority fee, anti-sandwich, and slippage settings."
Context: 跟单配置包括：被跟地址、固定买入金额、最大跟买上限、是否自动跟卖、止盈止损、防夹、滑点。当余额连续 3 次不足时系统自动停止跟单。
Confidence: high

**Claim 7: GMGN Bot 的标准止损设置为 -30% 到 -40%，止盈设置为 2X 保守 / 5X 激进，分批止盈策略（50% 在 2X 卖出，30% 在 5X 卖出，剩余 20% 持有）**
Source: Best GMGN Bot Settings (CoinCodeCap)
URL: https://coincodecap.com/best-settings-for-gmgn-bot
Date: 2026-05-15
Excerpt: "Stop-loss at -30% to -40% as standard floor, take-profit at 2X conservative or 5X aggressive. Scaled TPs (sell 50% at 2X, 30% at 5X, ride the remaining 20%) work well on memecoins."
Context: 自动卖出规则在服务器端执行，即使 Telegram 关闭也会触发。对于新币（Pump.fun），推荐滑点 10-15%（热门 15-20%），已建立代币 5-8%。
Confidence: high

**Claim 8: GMGN 提供三种滑点模式和三种 MEV 防护模式**
Source: Best GMGN Bot Settings (CoinCodeCap)
URL: https://coincodecap.com/best-settings-for-gmgn-bot
Date: 2026-05-15
Excerpt: "Auto Slippage — GMGN dynamically calibrates based on token liquidity and volatility; Turbo Slippage — Higher tolerance for fast swaps; Anti-MEV Slippage — Lower tolerance to protect against sandwich attacks... MEV protection: Off / Reduced / Secure — Secure routes through Jito's private mempool."
Context: Secure 模式通过 Jito 私有内存池发送交易，最大防夹保护但延迟更高。Reduced 为平衡模式。Off 模式最快但暴露于 MEV 攻击。Priority fee 标准 0.01-0.03 SOL，竞争激烈时 0.05-0.1 SOL。
Confidence: high

**Claim 9: GMGN 的 Anti-MEV 保护使用 Jito 处理器，在活跃 Solana 代币上产生可测量的更好的成交价**
Source: GMGN Review 2026 (ChainDecrypt)
URL: https://chaindecrypt.com/blogs/gmgn-ai-review-2026-solana-memecoin-hunting-tool-tested-by-real-trades/
Date: 2026-05-25
Excerpt: "The platform has built-in features that work on tokens using Jito processors, protecting against sandwich attacks... On active Solana tokens where MEV bots are aggressive, this protection produces measurably better fills. The cost is a minimum 0.002 SOL tip fee per transaction."
Context: 防夹功能通过将交易发送到安全 RPC 端点而非公共内存池，使 MEV 机器人无法看到交易。在热门代币上能显著减少滑点损失。
Confidence: high

**Claim 10: 社区封装了 Python WebSocket 客户端 GmGnAPI，支持实时新池、代币更新、钱包交易订阅**
Source: GmGnAPI GitHub (ChipaDevTeam/GmGnAPI)
URL: https://github.com/ChipaDevTeam/GmGnAPI
Date: 2024-01-15
Excerpt: "GmGnAPI provides real-time access to Solana blockchain data through GMGN.ai's WebSocket API with advanced features including intelligent filtering, data export capabilities, monitoring statistics, and automated alerting."
Context: 支持多链（Solana、Ethereum、BSC、Polygon），具备自动重连、指数退避、Pydantic 模型验证、速率限制、队列管理。可通过 pip install gmgnapi 安装。
Confidence: high

**Claim 11: GmGnAPI 提供四层交易机器人架构：数据层、信号层、执行层、风控层**
Source: GmGnAPI Documentation (Trading Bots)
URL: https://chipadevteam.github.io/GmGnAPI/trading-bots.html
Date: 2025
Excerpt: "A GmGnAPI-based trading bot has four layers: 1. Data Layer — GmGnAPI WebSocket stream; 2. Signal Layer — Your logic that decides whether a token event is worth acting on; 3. Execution Layer — The code that calls a DEX; 4. Risk Layer — Position sizing, max loss limits, stop losses, and circuit breakers."
Context: 文档提供新池狙击手代码示例，包含最大单笔交易金额（0.05 SOL）、每小时最大交易数（10 次）、熔断机制和基于时间的退出策略（5 分钟后自动卖出）。
Confidence: high

**Claim 12: 第三方 EVM 网格交易机器人 evm-grid-bot 已集成 GMGN 数据 API，支持 BSC 链自动化网格交易**
Source: evm-grid-bot (GitHub/fachebot)
URL: https://pkg.go.dev/github.com/fachebot/evm-grid-bot
Date: 2025
Excerpt: "EVMGridBot 是一个智能的网格交易机器人... 价格数据：GMGN API/OKX Web3 API... 智能网格交易：在用户设定的价格区间内自动执行低买高卖策略。"
Context: 使用 Go 1.24.1 开发，SQLite3 数据库，Telegram Bot 接口。默认配置包括每格大小 30 USDT、最大网格数量 10、止盈 6%、止损清仓、防瀑布开关（3 根 K 线跌幅 20% 触发）。可配置 Datapi 为 gmgn 或 okx。
Confidence: high

**Claim 13: GMGN 的追踪止盈追踪价格高点，在指定回撤百分比后触发卖出；适合 3-15 分钟的新币**
Source: Fastest Solana Sniper Bot 2026 (SolanaSniperBot)
URL: https://solanasniperbot.net/fastest-solana-sniper-bot-2026/
Date: 2026-02-24
Excerpt: "Trailing Take-Profit / Trailing Stop-Loss — Tracks price peak; fires after a specified drawdown % — rides momentum while protecting gains. Trailing options useful for fresh coins (Age 3-15m)."
Context: GMGN 的追踪止盈止损在 Telegram 中通过 /start → Settings → Auto Sell 设置。止损典型设置：-30% 卖出 100%。止盈 1：+50% 卖出 50%；止盈 2：+150% 卖出 50%。TP 总量必须 ≤ 100%。
Confidence: high

**Claim 14: 在 meme 币高波动环境中，固定百分比止损容易被噪音触发，但追踪止盈能捕获价格冲高的长尾收益**
Source: GMGN Trading Platform Review (MemeCoinTradingPlatforms)
URL: https://memecointradingplatforms.com/trading-platforms/gmgn-trading-review/
Date: 2025-04-13
Excerpt: "Trailing Take Profit (TTP) and Trailing Stop Loss. Your positions automatically adjust to get maximum gains with TTP enabled. The system tracks price increases and sells when it hits your specified drawback percentage. This helps secure your profits even when you're away from the market."
Context: 追踪止盈在 Meme 币的"冲向月球"阶段特别有效，因为价格可能在短时间内上涨数倍后迅速回落，固定止盈会提前退出。但回溯测试数据未公开，实际效果取决于回撤百分比设置（通常 5-15%）。
Confidence: medium

**Claim 15: gmgn-skills 支持 OpenClaw、Claude Code、Cursor、Cline、Codex CLI、OpenCode 六种 AI 客户端集成**
Source: GMGN Skills README
URL: https://github.com/GMGNAI/gmgn-skills
Date: 2026-06-12
Excerpt: "OpenClaw: Send the following prompt directly to test the query capabilities — 'Show me the trending tokens on Solana in the last 1 hour.'; Claude Code: Skills are automatically discovered when the package is installed as a plugin; Cursor: Skills are automatically discovered via the .cursor-plugin/ configuration."
Context: OpenClaw 是 2025 年底由 Peter Steinberger 推出的开源 AI Agent 框架，支持通过 Telegram/WhatsApp/Discord 执行复杂任务。通过 GMGN Skills，用户可用自然语言如 "buy 0.1 SOL of <token>" 完成交易。
Confidence: high

**Claim 16: OpenClaw 集成 GMGN Skills 需要生成 Ed25519 密钥对，在 gmgn.ai/ai 上传公钥获取 API key，配置 .env 文件**
Source: OpenClaw Solana Crypto AI Agents Guide (Skywork AI)
URL: https://skywork.ai/skypage/en/openclaw-solana-crypto-ai-agents/2052363994876448768
Date: 2026-01-31
Excerpt: "Step 2: Generating Keys and Installing Skills — Generate an Ed25519 key pair locally. Never share your private key. Upload your public key to the GMGN AI portal to receive an API key. Next, instruct your agent to install the necessary skills by typing: npx skills add GMGNAI/gmgn-skills."
Context: OpenClaw 在 GitHub 上获得超过 361,000 stars。通过 GMGN API，OpenClaw 代理可执行 sub-0.30-second 延迟的交易。支持的投资组合跟踪（45%）、自动交换（30%）、收益 farming（15%）和质押（10%）。
Confidence: high

**Claim 17: 2026 年 Solana AI Agent 市场已发展为数十亿美元垂直领域，AI Agent 占加密投资者兴趣的 62%（与 meme 币结合时）**
Source: AI Agents in Crypto 2026 Guide (Altrady)
URL: https://www.altrady.com/blog/cryptocurrency/ai-agents-in-crypto
Date: 2026-05-12
Excerpt: "By Q1 2026, AI agents accounted for 62% of investor interest in crypto when combined with memecoins. The AI agents sector alone has a market... AI agents on Solana are autonomous programs that combine Large Language Models with on-chain execution capabilities."
Context: Solana 的 400ms 区块时间、亚秒级最终性和低于 $0.001 的交易费用，使其成为 AI Agent 高频交易的首选链。主要项目包括 ai16z（AI DAO 基金管理）、Zerebro（跨平台内容代理）、GOAT（Truth Terminal 推动的 meme 币）。
Confidence: high

**Claim 18: 2026 年 AI Trading Agent 在 Solana meme 币交易中预计捕获 70% 的 meme 币交易量，远超传统交易 bot**
Source: Best AI Trading Agent for Solana Memecoins (GPTrader)
URL: https://gptrader.app/blog/best-ai-trading-agent-solana-memecoins-2026
Date: 2026-01-26
Excerpt: "By 2026, expect AI Trading Agents to capture 70% of memecoin volume, far outpacing bots. For traders frustrated with manual oversight, this is the autonomous evolution you've been waiting for."
Context: AI Trading Agent 使用 GPT-4、DeepSeek 等 LLM 进行推理，通过 LangChain 编排，结合 Solana RPC 和链上分析。&milo 是 Solana 原生 AI 组合管理器，使用 GPT-4 + Claude + DeepSeek 多模型，支持全自动交易（AutoTrade）或人工监督模式，零月费，仅按交易收取费用。
Confidence: medium

**Claim 19: GMGN 的 API 未向公众开放，仅提供 IP 白名单数据抓取，限速 2 次/秒，需提交交易记录和邀请码申请**
Source: Why is GMGN API Not Open to the Public? (Mobula)
URL: https://docs.mobula.io/guides/gmgn-closed-apis
Date: 2026-01-29
Excerpt: "GMGN has opted to keep its data API private. Instead, they provide access to their data crawling IP whitelist, but only for users with GMGN transaction records. To apply, users must submit their GMGN transaction address, invitation code, and IP address for whitelist approval. The API is heavily restricted, with a rate limit of just 2 requests per second."
Context: GMGN 关闭 API 的原因包括：保护 IP（反 MEV 引擎）、确保平台稳定性、订阅盈利策略、监管安全。开发者替代方案：使用 Jupiter、Mobula 或官方 gmgn-skills（通过 CLI 访问）。
Confidence: high

**Claim 20: 绕过 GMGN Cloudflare 防护的社区方案包括：住宅代理、TLS 指纹模拟（curl-cffi）、Stealth Playwright、Apify 爬虫**
Source: GMGN Scraping GitHub (bigdata5911/gmgnai-scraping)
URL: https://github.com/bigdata5911/gmgnai-scraping
Date: 2025-07-31
Excerpt: "async function getTrendingTokens(chain='eth', timePeriod='6h', orderBy='swaps') { const url = `https://gmgn.ai/defi/quotation/v1/rank/${chain}/swaps/${timePeriod}?...`; // Configure headers to bypass Cloudflare protection }"
Context: 社区公开的 REST API 端点结构：`https://gmgn.ai/defi/quotation/v1/rank/{chain}/swaps/{time_period}`。支持排序条件：volume、marketcap、swaps、holder_count、smartmoney、liquidity。时间周期：1m/5m/1h/6h/24h。但 Cloudflare 防护需要代理或浏览器自动化工具绕过。
Confidence: high

**Claim 21: Apify 平台上已有多个 GMGN 专用爬虫工具，支持钱包统计、Smart Degen 监控、钱包活动追踪**
Source: Apify GMGN Wallet Stat Scraper
URL: https://apify.com/muhammetakkurtt/gmgn-wallet-stat-scraper
Date: 2026-02-26
Excerpt: "GMGN Wallet Stat Scraper is a powerful web scraping tool... collects comprehensive information such as trading statistics, profit/loss ratios, and performance indicators from a wallet... Multi-Blockchain Support: Works on Ethereum, BSC, Base, Solana, Tron, and Monad networks."
Context: Apify 上的 GMGN 爬虫工具支持多钱包同时扫描、1d/7d/30d/全时间段统计、JSON/CSV/Excel 导出、代理支持。相关工具包括：GMGN Smart Degen Monitor Scraper、GMGN Wallet Activity Scraper、Crypto Wallet Performance Tracker。
Confidence: high

**Claim 22: 网格交易在震荡行情中有效，但在 Meme 币的 pump-and-dump 环境中极易产生单边行情损失；DCA 策略在 Meme 币中基本不适用**
Source: Grid Trading vs DCA Comparison (Streamline)
URL: https://www.streamline.cx/resources/blog/grid-trading-vs-dca-bots-which-strategy-wins/
Date: 2025-12-11
Excerpt: "The crypto graveyard is full of traders who ran Grid bots during a market crash or DCA bots during an unending bear trend... In the 'Moon Mission' scenario: A new meme coin or layer-1 is pumping. It goes up 10% every single day without stopping. Winner: Neither (Buy & Hold). If you run a Grid Bot here, it will sell all your coins within the first 15% move."
Context: Meme 币的极端波动（分钟级 10%+ 波动、单日归零或 100X）使网格交易极易"出范围"并遭受永久性损失。DCA 在 Meme 币上更危险，因为大多数 Meme 币最终归零，"平均下来只会更快亏钱"。
Confidence: high

**Claim 23: 马丁格尔策略在 Meme 币中风险极高，因为 Pump.fun 上 98.6% 的代币是 pump-and-dump，加仓只会扩大归零损失**
Source: Solidus Labs Solana Rug Pulls Report
URL: https://www.soliduslabs.com/reports/solana-rug-pulls-pump-dumps-crypto-compliance
Date: 2025-02-21
Excerpt: "A staggering 98.6% of tokens on Pump.fun collapse into worthless pump-and-dump schemes shortly after launch... The bonding curve is a pricing mechanism where token prices increase exponentially with each additional purchase, inherently benefiting early buyers and disadvantaging late entrants."
Context: 马丁格尔（加倍下注）在震荡市中通过加倍买入降低平均成本，但在 Meme 币中，由于 98.6% 的代币迅速归零，每次加倍都只是增加归零损失。DCA 计算器警告："Don't DCA into meme coins or projects without fundamentals. DCA amplifies both gains and losses — if a coin goes to zero, averaging down just loses money faster."
Confidence: high

**Claim 24: 自动化交易相比手动交易的核心优势：24/7 运行、微秒级执行、消除情绪偏差（减少 90% 心理错误）、一致的风控**
Source: Automated Crypto Trading Bot Advantages (Darkbot)
URL: https://darkbot.io/en/blog/automated-crypto-trading-bot-advantages-for-2026-profits
Date: 2026-03-06
Excerpt: "Automated bots deliver six distinct advantages over manual trading methods. They operate around the clock without breaks... AI-driven execution speed represents another major benefit... Automated trading bots reduce human psychological errors by up to 90%, improving consistency and profitability."
Context: 手动交易者的典型胜率仅 35-45%，而自动化 bot 可达 85%+。Bot 能同时管理多个交易对、执行多层级止盈和止损。但 backtest 过拟合、流动性约束、连接中断和错误配置是主要风险。
Confidence: medium

**Claim 25: 自动化交易系统在回测中通常比手动交易平均 outperform 6-8%，但 Meme 币市场的特殊风险（rug pull、honeypot）需要专门防护**
Source: Bitcoin Day Trading Bot (PocketOption)
URL: https://pocketoption.com/blog/en/post/bitcoin-day-trading-bot
Date: 2026
Excerpt: "Data demonstrates that automated systems consistently outperform manual trading by 6-8% on average. The key to success lies in proper configuration, regular monitoring, and adaptation to changing market conditions."
Context: 在 Meme 币市场中，自动化优势被特定风险抵消：98.6% 的 Pump.fun 代币是诈骗，honeypot 阻止卖出，MEV 三明治攻击造成 1-8% 额外损失。有效的自动化策略必须结合 GMGN 的 CA 安全检查、LP 燃烧验证、Dev Sell 保护。
Confidence: medium

**Claim 26: 2026 年 Solana AI Agent 项目如 ai16z、Zerebro、&milo 使用多模型 LLM（GPT-4 + Claude + DeepSeek）进行自主链上决策**
Source: &milo Review 2026 (ReviewNexa)
URL: https://reviewnexa.com/milo-review/
Date: 2026-02-27
Excerpt: "&milo is an AI-powered crypto portfolio manager built natively on the Solana blockchain... powered by a multi-model AI engine that uses GPT, Claude, and DeepSeek in tandem — each model handling different layers of the decision-making process."
Context: &milo 支持 Value Investor、Meme Momentum Scout、Conservative Value 等 37+ 策略。Arena 功能提供 90 天实盘竞赛，奖金 $1,000 + 50,000 Bones。完全非托管模式（Phantom/Solflare 钱包连接），零月费，仅按交易收取费用。
Confidence: high

**Claim 27: GMGN 的实时数据维度超过 500 个，包括 Smart Money 计数、KOL 持仓、老鼠仓比例、打包机器人暴露、狙击钱包数量、Rug 比例评分等**
Source: GMGN Skills README
URL: https://github.com/GMGNAI/gmgn-skills
Date: 2026-06-12
Excerpt: "500+ professional data dimensions... Smart money count (smart_degen_count) and KOL holders (renowned_wallets) — live; Rat trader ratio (rat_trader_amount_rate) — volume share from insider/sneak wallets; Bundler bot exposure (bundler_trader_amount_rate); Sniper wallets (sniper_count); Suspected insider hold rate (suspected_insider_hold_rate); Fresh wallet ratio (fresh_wallet_rate); Rug ratio score (0-1) + honeypot detection + wash-trade flag."
Context: 这些数据维度通过 gmgn-skills 的 API 实时获取，无需爬取网页或处理 Cloudflare。支持新代币发现（Trenches）、趋势代币排名、K-line 数据（1m/5m/15m/1h/4h/1d）、钱包持仓和活动追踪。
Confidence: high

**Claim 28: 社区交易员声称使用 Grok 构建 AI 交易机器人，3 天从 0.1 SOL 增长到 312 SOL，但该案例未经验证**
Source: （未能找到原始独立验证来源，仅作为背景信息提及）
URL: N/A
Date: 2025-2026
Excerpt: "社区已有交易员用 Grok 构建 AI 交易机器人，声称 3 天 0.1 SOL → 312 SOL。"
Context: 该声称流传于社交媒体和 Telegram 群组，但缺乏可验证的交易记录和第三方审计。考虑到 Meme 币市场的极端波动性和 survivorship bias（幸存者偏差），此类声称应视为未经证实的营销言论，而非可复制的策略基准。更可信的参考是 &milo 等已上线平台的实际性能数据。
Confidence: low

**Claim 29: 2026 年 Solana AI Agent 采用 x402 支付标准，日均交易量 $380K+，周增长率 750%**
Source: AI Agent Crypto Payment Trends 2026 (Tapbit)
URL: https://blog.tapbit.com/ja/ai-agent-crypto-payment-trends-2026-base-vs-solana-x402-standard-which-chain-settles-faster/
Date: 2026-01-08
Excerpt: "x402 protocol adoption accelerates: Daily Volume: $380K+ (750% WoW growth); Solana Share: Leading production deployments; Solana (x402): 1,267 TPS average; Finality: Solana sub-second vs Base ~12 seconds (62x difference)."
Context: Solana x402 标准在 AI Agent 支付中领先，因为 Agent 需要高频微交易。Solana 平均费用 <$0.001，而 Base 约为 <$0.01。Stripe 创始人 2026 年 2 月指出 AI Agent 最终需要每秒数十亿笔交易，Solana 的 Firedancer 扩展路线是唯一候选。
Confidence: high

**Claim 30: GMGN 的 GMGN_API_KEY 配置使用 IP 白名单机制，异常请求会被自动拦截**
Source: DragonClaw GMGN SKILL.md
URL: https://github.com/draguris/dragonclaw/blob/main/src/skills/gmgn/SKILL.md
Date: 2026-03-13
Excerpt: "IP whitelist on the API key automatically blocks abnormal requests... GMGN hosted wallet architecture means private keys are not stored locally by GMGN."
Context: 安全规则包括：默认滑点 10%、交易前确认、不记录私钥、合约安全检查（honeypot、高税、可铸造）。跨技能集成：GMGN trending + Binance meme-rush 综合发现、GMGN 安全 + Binance 审计双重验证。
Confidence: high

---

### References

[^1] GMGNAI/gmgn-skills GitHub. "GMGN OpenAPI skills for AI Agent." https://github.com/GMGNAI/gmgn-skills

[^2] GMGN Skills Quick Start (AI Agent). "Installation and configuration guide." https://github.com/GMGNAI/gmgn-skills/blob/main/Readme.md

[^3] GMGN Skills CLI Reference. "Swap, cooking, multi-swap commands." https://github.com/GMGNAI/gmgn-skills/blob/main/Readme.md

[^4] FollowIn. "GMGN Follow Whale Tutorial." https://followin.io/en/feed/14515025

[^5] CoinCodeCap. "Best GMGN Bot Settings for Solana Trading." https://coincodecap.com/best-settings-for-gmgn-bot

[^6] ChainDecrypt. "GMGN Review 2026: Solana Memecoin Hunting Tool." https://chaindecrypt.com/blogs/gmgn-ai-review-2026-solana-memecoin-hunting-tool-tested-by-real-trades/

[^7] ChipaDevTeam/GmGnAPI. "Python WebSocket client for GMGN." https://github.com/ChipaDevTeam/GmGnAPI

[^8] GmGnAPI Documentation. "Trading Bot Architecture." https://chipadevteam.github.io/GmGnAPI/trading-bots.html

[^9] fachebot/evm-grid-bot. "EVM Grid Trading Bot with GMGN API." https://pkg.go.dev/github.com/fachebot/evm-grid-bot

[^10] SolanaSniperBot. "Fastest Solana Sniper Bot 2026." https://solanasniperbot.net/fastest-solana-sniper-bot-2026/

[^11] MemeCoinTradingPlatforms. "GMGN Trading Platform Review." https://memecointradingplatforms.com/trading-platforms/gmgn-trading-review/

[^12] Skywork AI. "The Ultimate Guide to OpenClaw Solana Crypto AI Agents." https://skywork.ai/skypage/en/openclaw-solana-crypto-ai-agents/2052363994876448768

[^13] Altrady. "AI Agents in Crypto: 2026 Guide." https://www.altrady.com/blog/cryptocurrency/ai-agents-in-crypto

[^14] GPTrader. "Best AI Trading Agent for Solana Memecoins 2026." https://gptrader.app/blog/best-ai-trading-agent-solana-memecoins-2026

[^15] Mobula. "Why is GMGN API Not Open to the Public?" https://docs.mobula.io/guides/gmgn-closed-apis

[^16] bigdata5911/gmgnai-scraping. "GMGN API scraping tool." https://github.com/bigdata5911/gmgnai-scraping

[^17] Apify. "GMGN Wallet Stat Scraper." https://apify.com/muhammetakkurtt/gmgn-wallet-stat-scraper

[^18] Streamline. "Grid Trading vs. DCA — Which Strategy Wins?" https://www.streamline.cx/resources/blog/grid-trading-vs-dca-bots-which-strategy-wins/

[^19] Solidus Labs. "Solana Rug Pulls & Pump-and-Dumps." https://www.soliduslabs.com/reports/solana-rug-pulls-pump-dumps-crypto-compliance

[^20] Darkbot. "Automated Crypto Trading Bot Advantages for 2026." https://darkbot.io/en/blog/automated-crypto-trading-bot-advantages-for-2026-profits

[^21] PocketOption. "Bitcoin Day Trading Bot." https://pocketoption.com/blog/en/post/bitcoin-day-trading-bot

[^22] ReviewNexa. "&milo Review 2026." https://reviewnexa.com/milo-review/

[^23] Tapbit. "AI Agent Crypto Payment Trends 2026." https://blog.tapbit.com/ja/ai-agent-crypto-payment-trends-2026-base-vs-solana-x402-standard-which-chain-settles-faster/

[^24] DragonClaw. "GMGN Skill for AI Agent." https://github.com/draguris/dragonclaw/blob/main/src/skills/gmgn/SKILL.md

[^25] CoinCodeCap. "Top 5 Telegram Bots for Crypto." https://coincodecap.com/top-5-telegram-bots-for-crypto

[^26] QuickNode. "GMGN.AI by GMGN.AI Team." https://www.quicknode.com/builders-guide/tools/gmgn-ai-by-gmgn-ai-team

[^27] SolanaTools. "Solana Trading Bot Comparison 2026." https://solanatools.io/blog/solana-trading-bot-comparison-2026.html

[^28] SolanaTradingBots. "GMGN AI vs Photon." https://solanatradingbots.com/compare/gmgn-ai-vs-photon/

[^29] WalletMaster. "Wallet Master vs GMGN." https://www.walletmaster.tools/blog/wallet-master-vs-gmgn/

[^30] Dev.to (Steven). "Discover Trending Crypto Tokens with GMGN.AI API." https://dev.to/imcrazysteven/discover-trending-crypto-tokens-with-gmgnai-api-a-complete-developer-guide-33fc
