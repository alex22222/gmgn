## Dimension 07-08: 风险管理与合约安全

### Current State
GMGN 作为 Solana 及多链 meme 币交易的核心工具，其用户面临的风险维度极其复杂：从仓位管理、合约安全（貔貅币/延迟貔貅）、MEV 三明治攻击、滑点设置，到假聪明钱/假 KOL 识别、钱包分层架构、Telegram Bot 私钥托管、交易心理自律，以及不同司法管辖区的法律合规。当前研究覆盖了这 11 个关键领域的最佳实践、工具对比、量化参数与法律框架，形成了一套系统性的风险管理与合约安全指南。

### Key Evidence

Claim: Meme 币交易应严格限制仓位，meme 配置不超过总资产的 10%，单一币种不超过 2%，跟单本金占比 1%-5%。
Source: Grenade.tw / GMGN 完整教學
URL: https://grenade.tw/blog/gmgn-ai-tutorial/
Date: 2026-05-08
Excerpt: "資金分配：迷因幣配置 < 總資產 10%，單一幣種投入 < 2%（如 1 萬美元本金，單幣最多 200 美元）"
Context: 中文社区对 GMGN 交易者的资金分配建议，与英文社区的 0.25-1% portfolio per trade 基本一致。
Confidence: high

Claim: 更专业的 meme 币仓位管理建议为单币 0.25-1% 组合，日最大亏损 5%，使用 burner 钱包隔离风险。
Source: CoinCodeCap / Risk Management for Memecoin Signals
URL: https://coincodecap.com/5-platforms-for-base-memecoin-trading-signals
Date: 2025-11-13
Excerpt: "Cap trades at 0.25-1% of portfolio, 5% daily max. Use burner wallets to isolate risk; never average down blindly."
Context: Base 链 meme 币交易的风险管理框架，同样适用于 Solana 生态。
Confidence: high

Claim: Pump.fun 交易者应仅使用总加密资产的 5-15% 作为 meme 交易资金，且将其视为可能完全损失的"支出资本"。
Source: Altrady / Pump.fun & Solana Memecoin Trading Guide
URL: https://www.altrady.com/blog/crypto-trading-strategies/pump-fun-solana-memecoin-trading
Date: 2026-05-13
Excerpt: "Memecoin trading capital: 5-15% (fixed dollar amount, refresh only when overall portfolio grows). Memecoins are not investments. They are trades with high asymmetric payoff. Treat the allocation as expense capital."
Context: 来自专业交易终端的框架建议，强调将 meme 交易与核心持仓严格分离。
Confidence: high

Claim: 部分地址故意"杀跟单"——大额买入低流动性代币吸引跟单者，然后迅速卖出获利。
Source: Grenade.tw / GMGN 完整教學
URL: https://grenade.tw/blog/gmgn-ai-tutorial/
Date: 2026-05-08
Excerpt: "部分地址會刻意『殺跟單』，建議同時關注 3-5 個錢包分散風險"
Context: 中文社区明确识别了"杀跟单"风险，即智能钱地址可能故意制造跟单陷阱。
Confidence: high

Claim: 识别延迟单（杀跟单）的四大技巧：实时订单与历史记录矛盾验证、收益异常稳定警示、流动性验证与滑点分析、平台限制提现危险信号。
Source: FXVC 社区 / 如何识别与防范市场跟单中的延迟单陷阱
URL: https://www.163.com/dy/article/JS2R3CMC0556BWR9.html
Date: 2025-04-01
Excerpt: "1. 实时订单与历史记录的矛盾验证；2. 收益异常稳定的警示——若波动率低于2%，极可能为人工操控；3. 流动性验证与滑点分析——伪造平台滑点≈0；4. 平台借口与限制提现"
Context: 传统金融跟单领域的延迟单识别方法，同样适用于链上跟单陷阱的识别。
Confidence: medium

Claim: 合约安全检查的 10 项核心清单包括：合约是否开源、proxy/可升级性、owner 是否 renounce、税率修改权限、黑名单功能、LP 锁仓状态、持仓集中度、真实交易模拟、历史交易分析、老鼠仓比例。
Source: CSDN / 貔貅币识别与防御
URL: https://blog.csdn.net/qq_26437925/article/details/161545685
Date: 2026-05-30
Excerpt: 表格列出了检查项：合约是否开源、是否有 proxy/可升级、owner 权限、税率函数、LP 是否锁仓、持仓集中度、真实交易模拟、历史交易。以及老鼠仓比例不超过 20% 的建议。
Context: 技术社区系统整理的貔貅币识别人工排查清单，涵盖 Solidity 合约的核心安全检查点。
Confidence: high

Claim: 延迟貔貅的典型实现：合约用 proxy/setTaxRate，初始 0% 税，等流量上来 owner 调成 99%。
Source: CSDN / 貔貅币识别与防御
URL: https://blog.csdn.net/qq_26437925/article/details/161545685
Date: 2026-05-30
Excerpt: "合约用 proxy / setTaxRate(uint) 函数，初始 0% 税，等流量上来 owner 调成 99%。初期审计看不出问题，因为代码确实没毒，但 owner 有钥匙。"
Context: 延迟貔貅是技术层面最难检测的陷阱，需要持续监控 owner 权限和税率变化。
Confidence: high

Claim: 貔貅币检测的分层方案推荐：Layer 1 使用 GoPlus/Honeypot.is API；Layer 2 自建 Anvil fork 模拟买卖；Layer 3 行为指标打分+持续监控；Layer 4 静态分析+人工 review。
Source: CSDN / 貔貅币识别与防御
URL: https://blog.csdn.net/qq_26437925/article/details/161545685
Date: 2026-05-30
Excerpt: "Layer 1 GoPlus / Honeypot.is API... Layer 2 自建 Anvil fork 模拟买卖... Layer 3 行为指标打分 + 持续监控... Layer 4 静态分析 + 人工 review"
Context: 技术社区推荐的综合分层检测方案，可有效覆盖"延迟貔貅"的监控需求。
Confidence: high

Claim: 面向普通用户的现成检测工具包括：Honeypot.is（专门检测貔貅）、DEXTools/Dexscreener（集成安全分数）、Token Sniffer（百分制打分）、GoPlus Security（全链最广支持）。
Source: CSDN / 貔貅币识别与防御
URL: https://blog.csdn.net/qq_26437925/article/details/161545685
Date: 2026-05-30
Excerpt: "Honeypot.is...专门检测代币是否为貔貅币... DEXTools / Dexscreener...集成了安全检测分数... Token Sniffer...百分制打分... GoPlus Security...上面几家很多分数其实都在调用 GoPlus 的底层 API"
Context: 散户可快速使用的免费检测工具组合，交叉验证可挡掉 90% 以上貔貅币。
Confidence: high

Claim: Solana 上的 SPL Token 貔貅检测需检查：mint authority、freeze authority、代币交易历史是否异常、流动性是否锁定。
Source: 行至网 / Solana链上貔貅合约自动检测脚本工具
URL: https://www.xingzhi.io/definance/38691.html
Date: 2025-07-03
Excerpt: "检查 mint authority 和 freeze authority；检查代币交易历史是否异常（无卖出）；检查是否锁定流动性；使用 Solana JSON RPC 与 SPL Token Program"
Context: Solana 链与 EVM 链不同，需通过 RPC 检查 SPL Token 权限而非合约代码。
Confidence: high

Claim: Sandwich bots 在 Solana 上 16 个月内提取了 $370M-$500M，单一程序 `vpeNALD...Noax38b` 占据了近半数攻击。
Source: Sanj.dev / Solana MEV & Jito Explained
URL: https://sanj.dev/post/solana-mev-jito-deep-dive/
Date: 2026-04-03
Excerpt: "Sandwich bots extracted between $370M and $500M from Solana users over the past 16 months. A single program accounts for nearly half of all sandwich attacks."
Context: 2026 年最新数据揭示了 Solana MEV 攻击的严重规模，强调 Jito bundle 作为唯一有效防护手段。
Confidence: high

Claim: 2025 年 Solana 上出现新型"wide (multi-slot) sandwiches"——跨不同 leader 区块的夹单攻击，占所有三明治的 93%，提取超过 529,000 SOL。
Source: bloXroute / A New Era of MEV on Solana
URL: https://bloxroute.com/pulse/a-new-era-of-mev-on-solana/
Date: 2025-10-23
Excerpt: "wide (multi-slot) sandwiches — attacks where the frontrun and backrun occur across different leader slots — have exploded in prevalence, accounting for 93% of all sandwiches and extracting over 529,000 SOL in the past year."
Context: MEV 攻击已从公共 mempool 转移到验证者集合，Jito bundle 的单槽保护已不足。
Confidence: high

Claim: Jito Bundle 通过绕过公共交易管线直接送达 Jito Block Engine，使 MEV 机器人无法在交易确认前观察到用户交易，从而有效阻止绝大多数三明治攻击。
Source: Alphecca / What Is a Jito Bundle on Solana
URL: https://alphecca.io/en/blog/what-is-jito-bundle
Date: 2026-03-20
Excerpt: "When you send a transaction through a Jito Bundle, it bypasses the public transaction pipeline and goes directly to the Jito Block Engine — a private system where MEV bots cannot observe your transaction."
Context: Jito Bundle 是 Solana 上最广泛采用的 MEV 防护机制，约 95% 的 Solana 质押运行 Jito 验证器客户端。
Confidence: high

Claim: Paladin 提供 P3 Priority Port 快速通道和识别排除三明治攻击的能力，但截至 2025 年 3 月市场份额仅 5%，且已移除开源套利机器人。
Source: ChainCatcher / A Comprehensive Analysis of MEV on Solana
URL: https://www.chaincatcher.com/en/article/2174818
Date: 2025-03-30
Excerpt: "Paladin: VIP Frontrunning and Trade Protection. Current market share: 5%, launched at the end of 2023... P3 Priority Port... Identifying and Excluding Squeeze Attacks... Paladin Bot has been officially announced to be removed."
Context: Paladin 是 Jito 的替代方案，但市场份额较小，主要优势是反三明治攻击承诺。
Confidence: high

Claim: Jupiter Aggregator 于 2024 年 8 月推出动态滑点算法，根据市场条件、代币类型、交易池和最大滑点容忍度实时计算理想滑点阈值。
Source: Helius / Solana MEV Report
URL: https://www.helius.dev/blog/solana-mev-report
Date: 2025-01-15
Excerpt: "In August 2024, Jupiter Aggregator introduced dynamic slippage... optimizes slippage settings in real time, leveraging heuristics to calculate the ideal slippage threshold... considering current market conditions, token types, pools, and max slippage tolerance."
Context: Jupiter 的动态滑点是 Solana 上最受欢迎的零售交易滑点优化方案。
Confidence: high

Claim: GMGN 滑点设置建议：日常 0.5%，热门盘 5-10%，新币狙击 10-15%，热门发射 15-20%，成熟代币 5-8%。保守/标准/激进设置矩阵已被整理。
Source: CoinCodeCap / Best GMGN Bot Settings for Solana Trading
URL: https://coincodecap.com/best-settings-for-gmgn-bot
Date: 2026-05-15
Excerpt: 表格显示：Conservative 新币滑点 8-12%，Standard 10-15%，Aggressive 15-25%；成熟代币保守 3-5%，标准 5-8%，激进 8-12%。
Context: 这是经过 2026 年 5 月 Pump.fun 发射实测验证的滑点配置矩阵。
Confidence: high

Claim: GMGN 的 MEV 保护模式分为三档：Off（最低延迟，MEV 暴露）、Reduced（更快，适度保护）、Secure（默认，新发射推荐）。
Source: CoinCodeCap / Best GMGN Bot Settings for Solana Trading
URL: https://coincodecap.com/best-settings-for-gmgn-bot
Date: 2026-05-15
Excerpt: "MEV protection mode: Secure (default for new launches); Reduced (faster, moderate protection); Off (lowest latency, MEV exposed)."
Context: 三档 MEV 保护模式让用户在速度与防护之间权衡。
Confidence: high

Claim: GMGN 交易优先级费（Jito tip）建议：常规 0.01-0.03 SOL，竞争性发射 0.05-0.1 SOL，保守 0.005-0.01 SOL。
Source: CoinCodeCap / Best GMGN Bot Settings for Solana Trading
URL: https://coincodecap.com/best-settings-for-gmgn-bot
Date: 2026-05-15
Excerpt: "Priority fee (Jito tip): 0.01-0.03 SOL standard; 0.05-0.1 SOL competitive launches; 0.005-0.01 SOL conservative."
Context: 优先级费与 Jito tip 的合理配置直接影响交易在拥挤网络中的确认速度。
Confidence: high

Claim: GMGN 跟单最佳设置：关注 5-7 个 AI 过滤钱包，镜像比例 10-20%，要求胜率 >60% 且 30+ 笔交易、7 天以上历史。
Source: CoinCodeCap / Best GMGN Bot Settings for Solana Trading
URL: https://coincodecap.com/best-settings-for-gmgn-bot
Date: 2026-05-15
Excerpt: "Copy trading: 5-7 AI-filtered wallets, 10-20% mirror size, >60% win rate over 30+ trades, >7-day history."
Context: 跟单不是越多越好，信号过多会坍缩为噪音。
Confidence: high

Claim: 假 KOL/假聪明钱可通过链上声誉和异常评分引擎（CRASE）识别，包括：清洗交易环、时间爆发机器人、跨桥洗钱、空投农民集群、Sybil 观众膨胀器、累犯地址回收者。
Source: AJACCM / On-Chain Reputation and Anomaly Scoring
URL: https://ajaccm.com/journal/index.php/ajaccm/article/download/291/284
Date: 2025
Excerpt: 六类对抗模式：Wash-Trading Ring（3-20 个钱包循环交易）、Temporal Burst Bot（高频微交易）、Bridge Provenance Launderer（跨桥到新地址）、Airdrop Farmer Cluster（数百钱包刷空投）、Sybil Audience Inflator（KOL 控制 Sybil 钱包互动）、Recidivist Address Recycler（休眠后重新注册）。
Context: 学术论文级别的链上声誉评分系统，可用于检测假 KOL 和伪造的聪明钱行为。
Confidence: high

Claim: 钱包指纹识别（wallet fingerprinting）可通过资金流出模式识别同一实体的多个钱包集群，t-SNE 可视化可清晰分离不同实体。
Source: HAL / Fingerprinting Bitcoin entities using money flow
URL: https://hal.science/hal-04208864v1/file/s41109-023-00591-2.pdf
Date: 2023
Excerpt: "Our work demonstrates that out-flow fingerprinting is a valid approach for recognizing multiple clusters of the same entity."
Context: 资金流出指纹识别是链上追踪的核心技术，可检测由同一实体控制的多个"聪明钱"地址。
Confidence: high

Claim: 硬件钱包最佳实践包括：从官方渠道购买、手写助记词在物理介质（金属板）上、多份备份存放在不同地点、交易前测试恢复、定期固件更新。
Source: Cobo / 硬件钱包完全指南
URL: https://www.cobo.com/zh/post/the-complete-guide-to-hardware-wallets-from-personal-storage-to-enterprise-grade-security-solutions
Date: 2025-12-11
Excerpt: "从官方渠道购买...记录助记词：将 24 词抄写在纸张上或防水材料上，不要拍照、截图、输入电脑...多份备份：将副本存放在不同地点...测试恢复...定期固件更新"
Context: 企业级安全团队提供的硬件钱包安全指南。
Confidence: high

Claim: 分层钱包架构推荐：热钱包（日常交易，1-5% 资产）、温钱包（定期操作，10-20%）、冷存储（长期持有，75-90%）。
Source: Cobo / 硬件钱包完全指南
URL: https://www.cobo.com/zh/post/the-complete-guide-to-hardware-wallets-from-personal-storage-to-enterprise-grade-security-solutions
Date: 2025-12-11
Excerpt: "热钱包层：1-5% 的资产；温钱包层：10-20% 的资产；冷存储层：75-90% 的资产。"
Context: 企业级分层安全模型，平衡安全性与操作效率。
Confidence: high

Claim: 个人用户的助记词安全：必须手写、绝对离线、防火防水、不使用云存储或截图；高净值用户可进一步使用多签合约。
Source: 小狐狸钱包官方版 / 如何用分层冷备份保障资产长期安全
URL: https://www.yxgssc.com/article/34.html
Date: 2026-01-28
Excerpt: "官方一直着重强调，这串助记词要手抄在物理介质上，像金属助记词板，要放在绝对离线、有防火防盗功能的安全地点。"
Context: 钱包官方强调的安全实践，助记词是资产终极控制权所在。
Confidence: high

Claim: GMGN Telegram Bot 的钱包私钥存放于服务器，虽然官方声称安全，但建议不要存放大量资金，交易完成后应立即将资产转回自己的钱包。
Source: murmurcats.com / GMGN 是什麼？新手必學的鏈上交易工具
URL: https://murmars.com/gmgn/
Date: 2025-05-19
Excerpt: "GMGN Bot 的錢包私鑰存放於伺服器，雖然官方聲稱安全，但建議不要存放大量資金。交易完成後，應立即將資產轉回自己的錢包。"
Context: 这是所有 Telegram 交易 Bot 的固有风险：私钥托管在服务器端。
Confidence: high

Claim: GMGN Telegram Bot 是"快捷交易工具"而非完全去中心化的非托管钱包，用户应在设置后立即导出私钥并离线备份。
Source: SolanaTools / Gmgn.ai Solana Memecoin Sniper Bot Review
URL: https://solanatools.io/gmgn.html
Date: 2026-01-26
Excerpt: "Export your private key immediately after setup and back it up securely offline. Keep only active trading capital in the bot wallet — use Phantom or Ledger for any holdings you plan to keep longer than a few days."
Context: 第三方安全评估一致建议：Bot 钱包仅作为"周转交易账户"，利润定期转回自托管钱包。
Confidence: high

Claim: 假 Telegram Bot 是常见风险——GMGN 本身不是骗局，但假机器人、广告和克隆链接泛滥，绝不应信任 Telegram 内的"支持"消息或广告。
Source: SolanaTradingBots / GMGN AI How to Use
URL: https://solanatradingbots.com/gmgn-ai-how-to-use/
Date: 2026-03-23
Excerpt: "GMGN itself is not a scam, but fake Telegram bots, ads and clone links are common. Always use the official GMGN website or the official Telegram bot list and never trust 'support' messages or ads in Telegram."
Context: 钓鱼风险不仅存在于假 KOL，也存在于假 Bot 和假客服。
Confidence: high

Claim: 交易心理自律的六大策略：1) 创建详细交易计划（入场/出场/仓位）；2) 练习正念冥想；3) 使用止损订单；4) 保持交易日志；5) 设置日/周最大回撤限制；6) 使用模拟账户练习。
Source: FundYourFX / Trading Psychology Dealing With FOMO and Revenge Trading
URL: https://fundyourfx.com/trading-psychology-dealing-with-fomo/
Date: 2025-03-24
Excerpt: "1. Create a Detailed Trading Plan... 2. Practice Mindfulness... 3. Use Stop-Loss Orders... 4. Keep a Trading Journal... 5. Take Breaks... 6. Practice on a Demo Account."
Context: 交易心理学领域公认的 FOMO 和报复性交易对抗框架。
Confidence: high

Claim: 交易纪律的每日习惯框架包括：盘前例行稳定情绪、每笔交易记录日志、尊重止损、日亏损上限后停止、每周自我复盘。
Source: TSG Brokers / Trading Psychology Tips for Beginners
URL: https://tsgbrokers.com/trading-psychology-tips-for-beginners-handling-fomo-and-revenge-trading/
Date: 2026-06-18
Excerpt: 表格显示：Pre-market routine（每日）、Journaling every trade（每笔）、Respecting stop-losses（每笔）、Stopping after daily loss（每session）、Weekly self-review（每周）。
Context: 纪律不是天生特质，而是通过重复结构化习惯建立的技能。
Confidence: high

Claim: 正念训练可识别 FOMO 和报复性交易的冲动而不立即行动，在决策中创造暂停和反思的空间。
Source: MindOwl / How Mindfulness Kills FOMO And Revenge Trading
URL: https://mindowl.org/how-mindfulness-kills-fomo-and-revenge-trading/
Date: 2025-05-01
Excerpt: "Mindfulness teaches you to recognize these feelings without acting on them, fostering a sense of clarity in your decision-making."
Context: 正念的核心是"觉察而不反应"，对高波动的加密货币交易尤其有效。
Confidence: high

Claim: 美国 IRS 要求中心化交易所从 2025 年 1 月 1 日起记录用户数字资产交易，2026 年初向用户和 IRS 报送新表格 1099-DA。
Source: ChainCatcher / Hotcoin Research 加密监管大逆转
URL: https://www.chaincatcher.com/article/2231456
Date: 2025-12-21
Excerpt: "中心化交易所和服务商...将从 2025 年 1 月 1 日起记录用户数字资产交易，在 2026 年初向用户和 IRS 报送新表格 1099-DA。"
Context: 美国加密货币税务报告框架正式落地，但 DeFi 协议（如 Uniswap）被豁免。
Confidence: high

Claim: 中国大陆地区对加密货币征税无明确规定，但个人持有和交易行为在法律灰色地带；香港对加密货币交易利润征收 16.5% 利得税。
Source: 德和衡 / 田小皖：全球加密货币税务政策概述
URL: https://www.deheheng.com/content/31162.html
Date: 2024-06-19
Excerpt: "目前中国大陆地区针对加密货币征税问题并无明确的规定...中国香港地区...根据现行法律，纳税人应对收益征税..."
Context: 中国法律对加密货币的禁止态度与征税之间存在矛盾，香港则相对清晰。
Confidence: medium

Claim: 2025 年美国国会通过了 H.J. Res. 25，正式废止了要求 DeFi 平台向 IRS 报送 1099-DA 的规则——纯粹在区块链上自动运营的 DeFi 平台无需报送。
Source: ChainCatcher / Hotcoin Research 加密监管大逆转
URL: https://www.chaincatcher.com/article/2231456
Date: 2025-12-21
Excerpt: "该法案正式废止了财政部针对 IIJA 第 80603 条...纯粹在区块链上自动运营、不提供法币进出转换的 DeFi 平台，无需向税务机关报送 1099-DA 交易报告。"
Context: 美国 DeFi 用户暂获税务报告豁免，但 CEX 用户仍需遵守。
Confidence: high

Claim: 全球加密货币税务政策差异显著：德国持有超一年免税；法国利润统一 30% 税率；英国需缴纳资本利得税；阿联酋个人免税但企业需遵守企业税。
Source: PwC / 拨云见日潮起扬帆 (China Tax Review 2026)
URL: https://www.pwccn.com/zh/tax/china-tax-review-2026.pdf
Date: 2026-02-13
Excerpt: "德国...持有加密货币超过一年...免税...法国...利润按 30% 的统一税率征税...阿联酋...个人的加密货币活动...享受免税环境..."
Context: 不同司法管辖区的税务政策差异直接影响交易者的合规成本和策略选择。
Confidence: high

Claim: 中国 2025 年加密货币政策呈现"有限开放"特征：支持区块链供应链/版权应用，严控代币化融资，仅允许国有银行/持牌机构开展托管清算，禁止散户直接投机。
Source: 今日头条 / 中国加密货币政策展望
URL: https://www.toutiao.com/article/7477179779490267700/
Date: 2025-03-02
Excerpt: "技术应用先行...牌照试点探索...机构参与门槛：仅允许国有银行、持牌金融机构开展加密货币托管、清算等业务，防范散户投机风险。"
Context: 中国政策可能走向"合规白名单+技术备案制"的双轨监管。
Confidence: medium

Claim: 专业交易者的止盈阶梯策略：2x 卖 25%、3x 卖 25%、5x 卖 25%、10x 卖 25%；止损设在入场价 30-50% 下方；时间退出：6-12 小时无动静则离场。
Source: Altrady / Pump.fun & Solana Memecoin Trading Guide
URL: https://www.altrady.com/blog/crypto-trading-strategies/pump-fun-solana-memecoin-trading
Date: 2026-05-13
Excerpt: "Take-profit ladders: 2x, 3x, 5x, 10x (sell 25% at each)... Stop-loss: 30-50% below entry... Time exit: if no movement in 6-12 hours, exit."
Context: 预定义退出策略比任何入场策略更重要，纪律决定生存。
Confidence: high

Claim: 慢雾安全团队发现 GitHub 上的热门 Solana 工具（solana-pumpfun-bot）暗藏恶意 NPM 包，扫描用户电脑钱包和私钥文件并上传至攻击者服务器。
Source: 慢雾科技 / GitHub 热门 Solana 工具暗藏盗币陷阱
URL: http://mp.weixin.qq.com/s?__biz=MzU4ODQ3NTM2OA==&mid=2247502589
Date: 2025-07-03
Excerpt: "攻击者通过伪装为合法开源项目，诱导用户下载并运行恶意代码...扫描受害者电脑文件...如果发现钱包或私钥相关的内容或文件就上传到攻击者控制的服务器。"
Context: 开源工具的安全风险是 Solana 交易者面临的重要威胁，尤其是第三方 Bot 和脚本。
Confidence: high

Claim: Solana 代币假充值攻击是交易所层面的链下安全问题：攻击者创建 token-account 进行转移后转出，再将 owner 转移给交易所充值地址，使交易所误认为有真实充值。
Source: 慢雾科技 / Solana 生态安全和审计策略
URL: http://mp.weixin.qq.com/s?__biz=MzU4ODQ3NTM2OA==&mid=2247498888
Date: 2023-11-18
Excerpt: "攻击者创建一个 token-account，往这个账号里转移代币，然后转出，最后把这个 token-account 的 owner 转移给交易所的充值地址..."
Context: 慢雾安全团队公开的安全审计策略，涵盖了 Solana 特有的代币安全模型。
Confidence: high

Claim: 中心化质押池可能支持恶意验证者——2025 年分析发现某些验证者的"sandwich rate"显著偏高，但仍从热门质押池获得大量质押。
Source: Solana Compass / Scale or Die at Accelerate 2025
URL: https://solanacompass.com/learn/accelerate-25/scale-or-die-at-accelerate-2025-the-state-of-solana-mev
Date: 2025-05-20
Excerpt: "Some of these validators received substantial stake from popular stake pools, raising questions about the responsibility of stake pools in ensuring the integrity of the validators they support."
Context: MEV 风险不仅来自 Bot，还来自被质押池支持的恶意验证者。
Confidence: high

Claim: 专有 AMM（如 HumidiFi、SolFi、Tessera）通过私人 vault 管理流动性，不公开暴露，MEV 机器人无法进行三明治攻击，已占 Solana DEX 交易量 50% 以上。
Source: Odaily / L1 Value Capture Shrinks Significantly
URL: http://www.odaily.news/en/post/5209445
Date: 2026-02-26
Excerpt: "Proprietary AMMs account for over 50% of Solana DEX volume... Since liquidity is not publicly exposed, MEV bots cannot perform sandwich attacks."
Context: 协议层 MEV 防护的新方向——通过私有 AMM 从根本上消除三明治攻击的可能性。
Confidence: high

Claim: 2025 年全球加密货币监管呈现"从混沌到清晰"的转折：美国《GENIUS 法案》通过确立稳定币框架，《CLARITY 法案》明确 SEC 与 CFTC 管辖权，预计 2026 年市场结构法案落地。
Source: 天府财经 / 全球加密货币采用Top30地区2025年监管动态
URL: https://www.tianfufin.com/web3/331744.html
Date: 2026-01-07
Excerpt: "《GENIUS 法案》通过...《CLARITY 法案》...明确了 SEC 与 CFTC 的管辖权...预计 2026 年市场结构法案有望落地。"
Context: 全球监管清晰度提升正在重塑行业生态和格局。
Confidence: high

Claim: 慢雾安全团队指出做好安全需三个要素：要有安全预算、要进行持续审计、要有高管直接负责安全工作。
Source: 慢雾科技 / Solana 生态安全和审计策略
URL: http://mp.weixin.qq.com/s?__biz=MzU4ODQ3NTM2OA==&mid=2247498888
Date: 2023-11-18
Excerpt: "我们认为做好安全需要考虑三个重要因素：要有安全预算、要进行持续的审计、要有高管直接负责安全工作。"
Context: 安全不仅是技术问题，更是组织层面的治理问题。
Confidence: high

---

### 引用列表

[^1]: CoinCodeCap, "5 Platforms for Base Memecoin Trading Signals," 2025-11-13. https://coincodecap.com/5-platforms-for-base-memecoin-trading-signals
[^2]: Altrady, "Pump.fun & Solana Memecoin Trading Guide," 2026-05-13. https://www.altrady.com/blog/crypto-trading-strategies/pump-fun-solana-memecoin-trading
[^3]: Grenade.tw, "GMGN 完整教學2026," 2026-05-08. https://grenade.tw/blog/gmgn-ai-tutorial/
[^4]: FXVC 社区, "如何识别与防范市场跟单中的延迟单陷阱," 2025-04-01. https://www.163.com/dy/article/JS2R3CMC0556BWR9.html
[^5]: CSDN, "貔貅币 (Honeypot Token) 识别与防御," 2026-05-30. https://blog.csdn.net/qq_26437925/article/details/161545685
[^6]: 行至网, "Solana链上貔貅合约自动检测脚本工具," 2025-07-03. https://www.xingzhi.io/definance/38691.html
[^7]: Sanj.dev, "Solana MEV & Jito Explained," 2026-04-03. https://sanj.dev/post/solana-mev-jito-deep-dive/
[^8]: bloXroute, "A New Era of MEV on Solana," 2025-10-23. https://bloxroute.com/pulse/a-new-era-of-mev-on-solana/
[^9]: Alphecca, "What Is a Jito Bundle on Solana," 2026-03-20. https://alphecca.io/en/blog/what-is-jito-bundle
[^10]: ChainCatcher, "A Comprehensive Analysis of MEV on Solana," 2025-03-30. https://www.chaincatcher.com/en/article/2174818
[^11]: Helius, "Solana MEV Report," 2025-01-15. https://www.helius.dev/blog/solana-mev-report
[^12]: CoinCodeCap, "Best GMGN Bot Settings for Solana Trading," 2026-05-15. https://coincodecap.com/best-settings-for-gmgn-bot
[^13]: AJACCM, "On-Chain Reputation and Anomaly Scoring (CRASE)," 2025. https://ajaccm.com/journal/index.php/ajaccm/article/download/291/284
[^14]: HAL Science, "Fingerprinting Bitcoin entities using money flow," 2023. https://hal.science/hal-04208864v1/file/s41109-023-00591-2.pdf
[^15]: Cobo, "硬件钱包完全指南," 2025-12-11. https://www.cobo.com/zh/post/the-complete-guide-to-hardware-wallets-from-personal-storage-to-enterprise-grade-security-solutions
[^16]: murmurcats.com, "GMGN 是什麼？," 2025-05-19. https://murmars.com/gmgn/
[^17]: SolanaTools, "Gmgn.ai Solana Memecoin Sniper Bot Review," 2026-01-26. https://solanatools.io/gmgn.html
[^18]: SolanaTradingBots, "GMGN AI How to Use," 2026-03-23. https://solanatradingbots.com/gmgn-ai-how-to-use/
[^19]: FundYourFX, "Trading Psychology Dealing With FOMO," 2025-03-24. https://fundyourfx.com/trading-psychology-dealing-with-fomo/
[^20]: TSG Brokers, "Trading Psychology Tips for Beginners," 2026-06-18. https://tsgbrokers.com/trading-psychology-tips-for-beginners-handling-fomo-and-revenge-trading/
[^21]: MindOwl, "How Mindfulness Kills FOMO And Revenge Trading," 2025-05-01. https://mindowl.org/how-mindfulness-kills-fomo-and-revenge-trading/
[^22]: ChainCatcher, "Hotcoin Research 加密监管大逆转," 2025-12-21. https://www.chaincatcher.com/article/2231456
[^23]: 德和衡, "田小皖：全球加密货币税务政策概述," 2024-06-19. https://www.deheheng.com/content/31162.html
[^24]: PwC, "拨云见日潮起扬帆 (China Tax Review 2026)," 2026-02-13. https://www.pwccn.com/zh/tax/china-tax-review-2026.pdf
[^25]: 今日头条, "中国加密货币政策展望," 2025-03-02. https://www.toutiao.com/article/7477179779490267700/
[^26]: 慢雾科技, "GitHub 热门 Solana 工具暗藏盗币陷阱," 2025-07-03. http://mp.weixin.qq.com/s?__biz=MzU4ODQ3NTM2OA==&mid=2247502589
[^27]: 慢雾科技, "Solana 生态安全和审计策略," 2023-11-18. http://mp.weixin.qq.com/s?__biz=MzU4ODQ3NTM2OA==&mid=2247498888
[^28]: Odaily, "L1 Value Capture Shrinks Significantly," 2026-02-26. http://www.odaily.news/en/post/5209445
[^29]: 天府财经, "全球加密货币采用Top30地区2025年监管动态," 2026-01-07. https://www.tianfufin.com/web3/331744.html
[^30]: Solana Compass, "Scale or Die at Accelerate 2025," 2025-05-20. https://solanacompass.com/learn/accelerate-25/scale-or-die-at-accelerate-2025-the-state-of-solana-mev
[^31]: 小狐狸钱包官方版, "如何用分层冷备份保障资产长期安全," 2026-01-28. https://www.yxgssc.com/article/34.html
