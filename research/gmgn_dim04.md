## Dimension 05: 外盘策略与PVP博弈

### Current State

Meme Coin 的"外盘"（Outer Market）指的是代币从内盘（Pump.fun bonding curve 等发射平台）毕业迁移到开放 DEX（PumpSwap/Raydium 等）后的交易阶段。外盘交易分为"一段"（毕业初期的高波动快速博弈）和"二段"（PVP 冷却后的价值挖掘）。当前（2026年）市场环境呈现以下特征：

- Pump.fun 毕业率极低（仅约 0.63%-1.5%），绝大多数代币死在 bonding curve 阶段，幸存者进入外盘后仍面临极高归零风险
- 2025年超过 1160 万个加密项目失败，meme 币占绝大部分；Q4 单季度 770 万个代币停止交易
- Pump.fun 累计收入超过 $9.356 亿，平台成为最大赢家
- 2025年3月 PumpSwap 上线后取代 Raydium 成为毕业代币的主要流动性目的地
- AI Agent 发币（如 Truth Terminal 推动 $GOAT）成为新叙事，改变传统 PVP 格局
- 链上 PVP 日胜率<0.5，平均日收益为负，仅极少数地址能稳定盈利
- 公平发射（Fair Launch）表面公平，实际存在严重的"前100名vs后续参与者"的收益鸿沟：前100名获利300%，后续参与者亏损82%
- 捆绑交易（Bundling）、老鼠仓、洗盘交易等操纵行为在 82.8% 的高表现 meme 币中被检测到

### Key Evidence

**Claim 1: 外盘一段（毕业迁移阶段）的介入时机通常在市值 $30K-$70K 区间，快速 SOL 积累是 graduation 的最强预测信号**

Source: University of Pisa / Scuola Normale Superiore / University of Bologna 联合研究（Pump.fun 毕业预测论文）
URL: https://www.stratiumsol.com/blog/pump-fun-graduation-rate-token-success-signals
Date: 2026-03-14
Excerpt: "Pump.fun graduation rate is approximately 0.63%... graduation requires accumulating approximately 85 SOL on the bonding curve, corresponding to roughly a $69,000 market cap... the speed of SOL accumulation on the bonding curve (fastest accumulation through fewest trades is the strongest predictor)... the ratio of bot-like activity to human trading (high bot ratio suppresses graduation probability)"
Context: 学术研究基于 2025年9月数据，655,770个代币中仅4,338个毕业
Confidence: high

Source: Bitquery API 文档
URL: https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/pump-fun-to-pump-swap/
Date: N/A
Excerpt: "A Pump.fun token graduates when its bonding curve is fully sold out... the market cap typically approaches $30K–$35K... 'King of the Hill' Tokens (30K–35K Market Cap)"
Context: 技术文档说明 graduation 触发条件和市值区间
Confidence: high

Source: Pump.fun Bonding Curve 技术详解（CSDN）
URL: https://blog.csdn.net/WuLex/article/details/145327974
Date: 2025-01-23
Excerpt: "上线 Raydium 时的价格... 相较于虚拟池中的初始价格上升了约 14.64 倍... 募资完成后的总 SOL 数量 = 30+85=115 SOL"
Context: 详细计算了 graduation 瞬间价格跃升约14.64倍的机制
Confidence: high

**Claim 2: 外盘二段策略核心是"投研+耐心+分批"，在 PVP 冷却、价格下跌50-80%后寻找有价值资产，典型案例如 $AVA 从浮亏30%到最终涨至3亿**

Source: Web3Rebate 研报《Meme币链上交易必学打法：外盘二段与准上所资产的玩法揭秘》
URL: https://web3rebate.com/383.html
Date: 2025-03-05
Excerpt: "玩法上跟外盘二段有点像，但更强调确定性和资金量... 有人拿1000万美金投进去，赚了几千万浮盈... 2000万附近买入，平均成本1700万，1200万浮亏30%+，最终涨至3亿"
Context: 这是直接针对"外盘二段"策略的中文深度分析文章
Confidence: high

Source: 孤飞博客《MEME市场擒龙术（一）：短期抄底及如何盈利》
URL: https://onefly.top/posts/241220.html
Date: 2024-12-20
Excerpt: "RSI跌破20，成交量增加的同时出现阳线 = 强烈抄底信号... 分批买入，第一笔0.5sol，后续分笔买进了总计2sol... 460刀赚取了3500刀的利润，获利760%... 强迫自己按下sell"
Context: 详细实操案例：eliza 情绪恐慌后RSI+成交量抄底法
Confidence: high

Source: Murad 专访《Meme超级周期里，如何挖掘千倍金狗？》
URL: https://www.odaily.news/post/5198963
Date: 2024-10-10
Excerpt: "我筛选项目时主要看至少已有六个月历史的项目... 打造一个信仰或者社区建设，就像是飞机起飞，在起飞之前，飞机需要先加速... 时间是无法伪造的... 最大的成功是在1000万到3000万，或者1000万到4000万美元市值之间的项目"
Context: 知名Meme投资人Murad的核心投研框架，强调"时间"作为无法伪造的筛选条件
Confidence: high

**Claim 3: 准上所资产的判断标准聚焦赛道龙头、PMF清晰度、团队叙事可信度，适合大资金（数百万美金起步）的确定性投资**

Source: Web3Rebate 研报
URL: https://web3rebate.com/383.html
Date: 2025-03-05
Excerpt: "重点是对赛道龙头的判断... 产品有没有清晰的PMF（市场契合度），能不能长期站稳脚跟... 比如$Ai16Z，AI赛道的明星项目，团队和叙事都让人信服... 动辄几百万美金起步"
Context: 明确将准上所资产定义为"赛道龙头+大资金+确定性"的策略
Confidence: high

Source: ChainCatcher《从 $GOAT 的爆火看 Llama Land》
URL: https://www.chaincatcher.com/article/2149855
Date: 2024-11-01
Excerpt: "$GOAT 已经成为了 AI Meme 板块的龙头... A16z 创始人 Marc Andreessen 的推文进一步助燃... 市值在数小时内从1亿美元飙升至3.2亿美元... 截至本文撰写时，其市值已达6.4亿美元"
Context: $GOAT 作为准上所/赛道龙头的典型案例，从 Pump.fun 到6.4亿市值
Confidence: high

**Claim 4: PVP博弈中的庄家行为模式包括捆绑交易（Bundling）、老鼠仓、洗盘交易，82.8%的高表现meme币存在操纵证据**

Source: arXiv 论文《Investigating Market Manipulations in the Meme Coin Ecosystem》
URL: https://arxiv.org/html/2507.01963v2
Date: 2026-01-02
Excerpt: "82.8% of these high-performing meme coins exhibit evidence of market manipulation, including recurrent wash trading... Fresh Address Distribution: On average, these addresses control 40.25% of the token supply... Strategic Airdrop Distribution: 63.43% of tokens distributed via airdrops... 62.9% of pump and dumps execute rapidly"
Context: 学术论文对 meme 币生态的系统性操纵研究，数据来自2024-2025年
Confidence: high

Source: Bubblemaps 捆绑代币报告
URL: https://www.coingabbar.com/en/crypto-currency-news/bubblemaps-bundled-token-report
Date: 2025-11-29
Excerpt: "Bundled token: a coordinated insider scheme where developers use multiple wallets to snipe early supply, push prices up, and then dump on retail buyers... Minimum drawdown: 78%; Over 50% of tokens: down 99% or more; Average lifespan: less than 24 hours before a rug or halt... US dominates: over 50% of these projects are connected to U.S. accounts"
Context: Bubblemaps 对捆绑代币的链上分析，揭示美国主导 Solana meme 币骗局
Confidence: high

Source: PANews《MEME巨鲸交易密码：高额收益盈下的高频博弈与隐秘操纵》
URL: https://www.panewslab.com/zh/articles/44e636fc-7462-4d75-aa94-85d1b537d089
Date: 2025-08-04
Excerpt: "Cented 这个地址很可能是某些'阴谋集团'地址的其中一个盈利地址... 该地址所谓的收益，多数情况下是其他地址故意买进抬高价格所致... 左手倒右手... 保留Cented这个地址长期显示盈利，是为了让一个地址成为'聪明钱'，以便有更多人跟单"
Context: 链上分析师对"聪明钱陷阱"的揭露——部分地址的盈利是内部操纵的结果
Confidence: medium

**Claim 5: 筹码高度集中是核心风险指标，Top10持仓>40%（排除LP）应直接排除；池子/市值比率30-60%是健康区间；静态可提取价值仅为市值15-30%**

Source: PANews《PVP被他们玩穿了？"链上皇"们的交易模式分析》
URL: https://www.panewslab.com/zh/articles/o7zrarle
Date: 2024-10-30
Excerpt: "主流的池子/市值比率在30%～60%之间... 全体holder的静态实际可提取价值，只有它们市值的15%～30%... meme币成功率极低（约1.63%），且大部分代币生命周期仅48小时"
Context: 对链上PVP皇交易模式的系统性分析，包含资金管理和标的选择策略
Confidence: high

Source: AI-FRB《Solana Meme Coin Trading Strategy》
URL: https://ai-frb.com/blog/ultimate-solana-meme-coin-strategy
Date: 2026-05-10
Excerpt: "Contract Security Scan: Instantly discard any contract where Mint Authority is active or the Top 10 holders own >40% of the supply (excluding the LP pool)... Liquidity Threshold: The pool must have a minimum of 20 SOL in initial locked liquidity"
Context: 数据驱动动量狙击策略的安全扫描规则
Confidence: high

Source: Ai 姨分析（ChainCatcher）
URL: https://www.chaincatcher.com/article/2172894
Date: 2025-03-17
Excerpt: "$mubarak 当前市值约为1.34亿美元，24小时交易额达8810万美元，但流动性池深度仅为448万美元，仅占日交易量的5%... 榜一地址若市价全部出售，将面临超过50万美元的滑点损失"
Context: 流动性深度严重不足导致大额持有者无法出货的实际案例
Confidence: high

**Claim 6: 成功的外盘二段抄底案例：$AVA（2000万→3亿）、$eliza（460刀→3500刀，760%）、GOAT（2PYWK早期买入，最高5678倍）**

Source: Web3Rebate 研报（$AVA案例）
URL: https://web3rebate.com/383.html
Date: 2025-03-05
Excerpt: "$AVA：2000万附近买入，平均成本1700万，1200万浮亏30%+，最终涨至3亿"
Context: 外盘二段大资金耐心建仓的实盘案例
Confidence: high

Source: 孤飞博客（$eliza案例）
URL: https://onefly.top/posts/241220.html
Date: 2024-12-20
Excerpt: "460刀赚取了3500刀的利润，获利760%... 市值为7m... 分批卖出了三次，每次20%~30%不等... 在70m的位置卖出了剩下的所有"
Context: 小资金外盘二段抄底的详细实操记录
Confidence: high

Source: PANews / Odaily（GOAT聪明钱分析）
URL: https://www.odaily.news/post/5199187
Date: 2024-10-20
Excerpt: "2PYWK在开盘后1小时25分左右开始买入，当时GOAT的市值还不到5万美元... 最初的持股如果不卖出截至10月17日可达到430万美元，最高倍数5,678倍... 在Pump.fun上交易他就已经获利4 SOL左右，所以在第二次买入5 SOL的时候，他的成本几乎可以忽略不计"
Context: GOAT作为Pump.fun毕业代币的典范，早期聪明钱的操作逻辑
Confidence: high

**Claim 7: 失败案例：外盘追高被套（HdxkiX抢GOAT开盘被套90%）、SICK狙击失败（2分钟冲至500万后跌60%）、抄底抄在半山腰**

Source: PANews / Odaily（GOAT失败案例）
URL: https://www.odaily.news/post/5199187
Date: 2024-10-20
Excerpt: "HdxkiX买入时正是GOAT拉升的过程，在短短5分钟内拉升了5倍... 随后GOAT的价格一落千丈，快速跌去了90%左右... 如果以他最初买入的数量持仓到最后最高可获利1036万美元，但他仅持仓约4小时就开始出货"
Context: 抢开盘+重仓买入在拉升过程中的典型失败案例
Confidence: high

Source: Odaily（SICK狙击失败）
URL: https://www.odaily.news/post/5198171
Date: 2024-09-04
Excerpt: "SICK开盘2分钟后市值就被狙击者冲到了500万美元左右，20分钟市值到达680万美元峰值，然后迅速崩盘下跌，目前距高点跌去60%"
Context: 防狙击功能失效后的狙击崩盘案例
Confidence: high

Source: 多家财经媒体（抄底半山腰分析）
URL: https://ag.yueniuzq.com/stock/left-side-trading-bottom-fishing-traps/
Date: 2026-04-15
Excerpt: "投资者屡屡在逆势交易中'抄底死在半山腰'，核心原因在于锚定前期高点导致对下跌空间估计不足，同时'猜底'思维极易引发过早逆势重仓的风险... 没有设置股票止损保护的左侧抄底，最终大概率会导致资金深度套牢"
Context: 对抄底抄在半山腰的系统性分析，解释了锚定效应和猜底陷阱
Confidence: high

**Claim 8: 不同资金规模的策略差异：小资金快进快出做波段（单笔$200-400，止损-10%~-15%），大资金做趋势耐心持有（分批建仓，不设明确止损）**

Source: PANews（链上皇交易模式分析）
URL: https://www.panewslab.com/zh/articles/o7zrarle
Date: 2024-10-30
Excerpt: "2zBoK：主仓位20-30%总资金，投机仓5-10%，30%利润快速回本，50%利润减半仓位... 52dq6：标准仓位$300-500，重点项目$1000-3000，快速止损-15%，普通止损-30%，最大止损-50%... BieeZ：单笔止损-8%，总仓止损-15%，浮盈止损回撤超过30%"
Context: 对8个链上PVP皇地址交易模式的详细分析
Confidence: high

Source: 知乎专栏（大资金趋势 vs 小资金波段）
URL: https://zhuanlan.zhihu.com/p/431058341
Date: 2021-11-09
Excerpt: "小资金帐户做波段就是要坚持积少成多的原则... 大资金做趋势，小资金做波段这也成为了期货投机市场的普遍规律... 小资金帐户错过行情不难受，不追涨杀跌，一心一意按照自己的策略尽量想办法抓住每一个波段的利润"
Context: 传统交易市场的大资金/小资金策略差异，在Meme市场同样适用
Confidence: medium

Source: Wesley 专访（Odaily）
URL: https://www.odaily.news/zh-CN/post/5207570
Date: 2025-11-14
Excerpt: "Meme币的话，最重要看题材和叙事，再用Bubblemaps看筹码分散程度... Meme币我只小仓位玩，比如之前买某安的4，就只买了15万美金，最高点能有500万美金回报... 大部分以现货为主，少部分加一点杠杆"
Context: A9巨鲸Wesley的跨周期交易认知，强调Meme币小仓位+题材叙事
Confidence: high

**Claim 9: 2026年PVP环境因AI发币、PumpSwap、公平发射悖论而深刻变化，毕业率仅0.63%，1160万项目失败**

Source: Yahoo Finance / CoinGecko
URL: https://finance.yahoo.com/news/meme-coins-bear-brunt-11-075657177.html
Date: 2026-01-12
Excerpt: "More than 11.6 million crypto projects failed in 2025, with meme coins hit hardest. An October market crash accelerated failures, wiping out 7.7 million tokens in Q4... The launch of pump.fun in early 2024 made it easier than ever to deploy new tokens"
Context: 2025年项目失败数量创历史纪录，meme币是重灾区
Confidence: high

Source: AInvest（2026年AI驱动Meme币复兴）
URL: https://www.ainvest.com/news/ai-driven-meme-coin-renaissance-strategic-entry-points-2026-2601/
Date: 2026-01-30
Excerpt: "The cryptocurrency landscape in 2026 is witnessing a seismic shift as artificial intelligence (AI) tools, social prediction markets, and blockchain infrastructure converge to redefine meme coin dynamics... AI models are now embedded into this ecosystem to analyze on-chain data and social sentiment"
Context: 2026年AI工具、社交预测市场和区块链基础设施的融合正在重新定义meme币
Confidence: high

Source: Tapbit（2026年Solana Meme币市场）
URL: https://blog.tapbit.com/solana-meme-coins-hit-6-7b-market-cap-in-2026-pump-fun-pivot-top-tokens-tapbit-trading-strategies/
Date: 2026-01-23
Excerpt: "Daily meme coin launches still exceed 30,000, but monthly DEX volume has cooled from a peak of $11.7B to around $2.4B... Pump.fun's strategic pivot to infrastructure funding... $3M Pump Fund (funding 12 startups at $10M valuations)"
Context: 2026年初Solana meme币总市值67亿，但月度DEX交易量从117亿冷却至24亿
Confidence: high

Source: AUC Journal（Pump.fun案例研究）
URL: https://aucjc.ro/wp-content/uploads/2025/07/aucjcm-11-15-38.pdf
Date: 2025
Excerpt: "Wallet Profitability: Wallets with >$10k profit: ~0.4-0.5%... Token Survival Rate: 93% of all tokens showing no trading activity after just one week... This is not a market experiencing failures; this is a market designed to produce failures as its primary output"
Context: 学术论文对Pump.fun的系统性批判，揭示仅0.4-0.5%的钱包盈利超过$10k
Confidence: high

**Claim 10: 判断"一波流"vs"有持续性项目"的核心在于：时间（至少6个月社区建设）、叙事独特性、筹码分散度、团队透明度和产品PMF**

Source: Murad 专访
URL: https://www.odaily.news/post/5198963
Date: 2024-10-10
Excerpt: "至少已有六个月历史的项目... 时间是无法伪造的... 市值在2000万美元以下盘整了一年，没有爆发，但也没有消亡，那就是一个值得关注的信号... 核心持有者不断通过定投来从那些不信者手中吸纳币种... 偏向于'真'Meme或带有某种运动/宗教氛围的项目"
Context: Murad的"时间筛选法"是判断持续性项目的核心框架
Confidence: high

Source: Sumsub（Pump-and-Dump vs Rug Pull）
URL: https://sumsub.com/blog/pump-dump-vs-rug-pull/
Date: 2026-06-11
Excerpt: "Many meme coins have little or no underlying utility, revenue, or long-term development plan. Their price often depends on attention, humor, momentum, and the hope that someone else will buy later at a higher price... The safest rule is to treat meme coins as extreme-risk speculation"
Context: 2026年最新分析，指出缺乏实用性和长期计划的meme币本质上依赖" greater fool"
Confidence: high

Source: arXiv（Pump.fun毕业预测论文）
URL: https://www.stratiumsol.com/blog/pump-fun-graduation-rate-token-success-signals
Date: 2026-03-14
Excerpt: "Why do some pump.fun tokens dump right after graduation? The researchers documented systematic pre-graduation selling by token creators... Buyers who enter at or immediately after graduation are frequently buying into creator distribution rather than continued organic momentum"
Context: 毕业即暴跌的系统性原因：开发者在graduation前系统性抛售
Confidence: high

---

### 引用列表

[^1]: https://www.panewslab.com/zh/articles/wqxifa92 - 如何玩转币安链Meme？猎币策略与工具盘点 (2025-03-19)
[^2]: https://www.120btc.com/baike/coin/454869002.html - Meme币投资策略！如何用社交与财务数据判断模因币发展 (2024-05-17)
[^3]: https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/pump-fun-to-pump-swap/ - Pump.fun to PumpSwap API - Token Migration Tracking
[^4]: https://arxiv.org/html/2602.14860v1 - Predicting the success of new crypto-tokens: the Pump.fun case (2026-02-16)
[^5]: https://shyft.to/blog/how-to-stream-bonding-curve-transactions-on-pumpfun - How to stream Bonding Curve Transactions on Pumpfun (2026-01-22)
[^6]: https://blog.csdn.net/WuLex/article/details/145327974 - PUMP.FUN的Bonding Curve定价机制原创 (2025-01-23)
[^7]: https://www.panewslab.com/zh/articles/o7zrarle - PVP被他们玩穿了？"链上皇"们的交易模式分析 (2024-10-30)
[^8]: https://www.odaily.news/post/5199187 - 解读GOAT上的聪明钱买入地址，MEME交易策略比运气更加重要 (2024-10-20)
[^9]: https://www.chaincatcher.com/article/2138633 - 利用链上工具建立交易策略的3个基本步骤 (2024-08-16)
[^10]: https://www.panewslab.com/zh/articles/44e636fc-7462-4d75-aa94-85d1b537d089 - MEME巨鲸交易密码：高额收益盈下的高频博弈与隐秘操纵 (2025-08-04)
[^11]: https://finance.sina.cn/blockchain/2024-10-17/detail-incsuuyn0044784.d.html - 如何发现百倍机会？Meme币工具大全 (2024-10-17)
[^12]: https://www.stratiumsol.com/blog/pump-fun-graduation-rate-token-success-signals - Pump.fun Graduation Rate: Only 0.63% of Tokens Survive (2026-03-14)
[^13]: https://www.soltokencreator.io/blog/pump-fun-graduation-explained - Pump.fun Graduation Explained (2026-03-09)
[^14]: https://www.bee.com/22586.html - The real data of pump.fun: 1.4% graduation rate, only 3% of users earn more than $1,000
[^15]: https://www.panewslab.com/zh/articles/lye07npn - 对比解读发币平台：从野蛮爆发走向精细化运营 (2025-05-19)
[^16]: https://www.sohu.com/a/891392350_422301 - Solana链上Meme热潮回归：公平发射平台Boop.fun (2025-05-02)
[^17]: https://arxiv.org/html/2507.01963v2 - Investigating Market Manipulations in the Meme Coin Ecosystem (2026-01-02)
[^18]: https://www.coingabbar.com/en/crypto-currency-news/bubblemaps-bundled-token-report - Bubblemaps Bundled Token Report (2025-11-29)
[^19]: https://ai-frb.com/blog/ultimate-solana-meme-coin-strategy - Solana Meme Coin Trading Strategy: Risk, Liquidity & Timing (2026-05-10)
[^20]: https://coconote.app/notes/79176b00-ef2c-42eb-979c-4b6c500577c8/transcript - Insights on Meme Coin Trading Strategies (2025-02-13)
[^21]: https://storm.partners/blog-post/meme-coin-mania-on-pump-fun-an-economic-and-legal-analysis - Meme Coin Mania on Pump.fun: An Economic and Legal Analysis (2025-11-12)
[^22]: https://aucjc.ro/wp-content/uploads/2025/07/aucjcm-11-15-38.pdf - PUMP.FUN AND MEME-COINS: A CASE STUDY (2025)
[^23]: https://web3rebate.com/383.html - Meme币链上交易必学打法：外盘二段与准上所资产的玩法揭秘 (2025-03-05)
[^24]: https://onefly.top/posts/241220.html - MEME市场擒龙术（一）：短期抄底及如何盈利 (2024-12-20)
[^25]: https://www.odaily.news/post/5198963 - 专访Murad：Meme超级周期里，如何挖掘千倍金狗？ (2024-10-10)
[^26]: https://www.chaincatcher.com/article/2149855 - 从 $GOAT 的爆火看 Llama Land (2024-11-01)
[^27]: https://www.odaily.news/post/5198171 - 防狙击Meme首秀翻车，想挑战Pump.fun的SICK引争议 (2024-09-04)
[^28]: https://ag.yueniuzq.com/stock/left-side-trading-bottom-fishing-traps/ - 逆势交易的死穴：为什么你总是抄底死在半山腰 (2026-04-15)
[^29]: https://www.odaily.news/zh-CN/post/5207570 - 对话 A9 巨鲸 Wesley (2025-11-14)
[^30]: https://finance.yahoo.com/news/meme-coins-bear-brunt-11-075657177.html - Meme Coins Bear the Brunt as 11.6M Crypto Projects Fail in 2025 (2026-01-12)
[^31]: https://www.ainvest.com/news/ai-driven-meme-coin-renaissance-strategic-entry-points-2026-2601/ - The AI-Driven Meme Coin Renaissance (2026-01-30)
[^32]: https://blog.tapbit.com/solana-meme-coins-hit-6-7b-market-cap-in-2026-pump-fun-pivot-top-tokens-tapbit-trading-strategies/ - Solana Meme Coins Hit $6.7B Market Cap in 2026 (2026-01-23)
[^33]: https://www.ainvest.com/news/resurgence-meme-coin-platforms-pump-fun-poised-dominance-2026-2601/ - The Resurgence of Meme Coin Platforms (2026-01-27)
[^34]: https://www.chaincatcher.com/article/2172894 - 分析：$mubarak 流动性池深度仅为日交易量5% (2025-03-17)
[^35]: https://www.dlnews.com/articles/defi/pumpfun-revenue-falls-to-10-month-low/ - Pump.fun revenue falls to 10-month low (2025-07-29)
[^36]: https://septimlabs.com/tools/pumpfun-bonding/ - Pump.fun Bonding Curve Simulator (2026-05-03)
[^37]: https://docs.chainstack.com/docs/solana-listening-to-pumpfun-migrations-to-raydium - Solana: Listening to pump.fun migrations to PumpSwap (2026-06-25)
[^38]: https://www.smithii.io/en/how-pump-and-dump-meme-coin/ - How to Pump and Dump a Meme Coin (2025-06-02)
