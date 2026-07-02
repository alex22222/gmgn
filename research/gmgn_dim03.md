## Dimension 04: 内盘扫链与金狗发现策略

### Current State
GMGN 是当前 Solana Meme Coin 扫链与金狗发现的主流工具平台，集扫链面板、交易执行、聪明钱追踪、合约安全检测于一体。2026年，Pump.fun 生态已从 Raydium 迁移全面转向 PumpSwap，代币生命周期进一步缩短，AI 狙击 Bot 与反狙击基础设施（Bundled Launch、自动 LP 销毁）成为主流竞争维度。手动扫链在速度和信息处理量上已显著落后于自动化工具，但人类叙事判断和异常识别仍具不可替代性。金狗发现的核心方法论围绕"安全筛选 + 叙事判断 + 时机把握"三轴展开，成功率极低（仅约1-2%代币能毕业），但早期捕获的回报可达数百至数千倍。

### Key Evidence

Claim: GMGN 扫链操作流程为：打开 gmgn.ai → 选择 SOL 链 → 点击 Meme → 选择 Pump 平台 → 进入三列面板（新创建/即将打满/已开盘）→ 右上角设置快速买入参数 → 点击代币进入交易面板 → 检查右下角安全指标 → 查看中间 K 线下方持仓分类 → 执行买入或快捷买入。连接 Telegram Bot 可提升交易速度并启用自动狙击/跟单功能。
Source: 深潮TechFlow / Odaily / 币币情
URL: https://www.panewslab.com/zh/articles/wxotn8i4 / https://www.odaily.news/post/5199894 / https://www.68bbq.com/news/detail/82039
Date: 2024-11-20
Excerpt: "点击'meme',选择'sol链'，选择'pump平台'，点击'pump'。右上角圈出来的'快速买入'对应着买入部分的设置，可以设置'购买数量'，'止盈止损'等参数，这个功能可以让你在扫链面板不查看'代币详情'的情况下直接买入，快人一步。"
Context: 多源中文教程共同确认的标准操作流程，适用于新手到进阶用户。
Confidence: high

Claim: Pump.fun 内盘（尚未迁移流动性）每日发行数万代币，但毕业率仅约0.7%-1%（每日毕业约200-400个）。毕业阈值约为85 SOL（约$69,000市值），达到后自动迁移至 PumpSwap（2025年3月起取代 Raydium），LP 代币自动销毁，无法撤回。
Source: 新浪财经 / 吴说区块链 / BullRank
URL: https://finance.sina.com.cn/blockchain/roll/2025-06-07/doc-inezfyqx9435744.shtml / https://bullrank.io/learn/raydium-migration-pump-fun-graduation
Date: 2025-06-07 / 2026-03-01
Excerpt: "每日毕业代币当天结束时平均FDV约8-10万美元，中位数约4000+美元，大部分代币一日归零；目前Pump Fun每日从内盘到外盘毕业率约为0.7%-1%。" "自2025年3月以来，代币迁移到PumpSwap...迁移是即时且免费的。"
Context: 关键数据支撑：毕业率极低，绝大多数内盘代币会快速归零。
Confidence: high

Claim: GMGN 金狗八大指标体系包括：①流动性池≥100 SOL；②1分钟真实交易>60笔或5分钟>600笔；③Mint权限已丢弃；④无黑名单；⑤烧池100%；⑥Top10持仓<30%；⑦老鼠仓<20%；⑧DEXScreener已付费（团队愿意投入广告费用）。
Source: Odaily / ChainCatcher / PANews
URL: https://www.odaily.news/en/post/5199963 / https://www.chaincatcher.com/en/article/2153149 / https://www.panewslab.com/en/articles/4eqt3xx6
Date: 2024-11-22
Excerpt: "Burn the pool: Check if the liquidity pool (LP) has been burned. The higher the burn rate, the lower the risk... 100% burn indicates that the project team cannot withdraw funds. Top 10 holdings: Observe whether the total holdings of the top 10 holders are less than 30% of the total supply. Monitor for rat trading: The lower the ratio, the better... recommended that the ratio does not exceed 20%."
Context: 多篇中英文教程一致确认这8大指标，作为筛选安全代币的核心框架。
Confidence: high

Claim: 叙事判断的核心方法：使用 GMGN 放大镜功能跳转 Twitter 搜索合约地址，观察 KOL 提及频率；点击 X 查看项目推特主页的活跃度、评论区互动、粉丝质量；分析是否有"新叙事+新大V+新梗+开盘不作恶+不搞捆绑"的特征；通过 MemeRadar 等插件查看推特改名次数、删推次数、KOL关注数量、AI叙事总结、社区讨论热度。
Source: 加密头条 / QQ新闻 / MemeRadar
URL: https://2jmtt.com/newbie/2501/202501248635.html / https://news.qq.com/rain/a/20241209A01VWC00 / https://www.offidocs.com/index.php/chromium-web-store/1742164-memeradar-extension
Date: 2025-01-24 / 2024-12-09
Excerpt: "好的叙事：新叙事、新的大V发的币、新的梗、开盘不作恶、不搞捆绑。" "KOL频繁提及的币，往往会吸引散户跟进...如果推特几乎没人讨论，说明这个币可能刚上线，热度较低。"
Context: 叙事判断是区分"流水盘"和"金狗"的关键软性指标，依赖社区经验和信息敏感度。
Confidence: high

Claim: 合约安全检查的详细清单包括：①Mint Authority 是否已撤销（防无限增发）；②Freeze Authority 是否已撤销（防冻结钱包）；③Blacklist 是否存在（防限制卖出）；④LP 是否已烧/锁（防撤池子跑路）；⑤Top10 持仓是否<30%（防集中砸盘）；⑥是否存在 Bundler/捆绑交易（防开发者自己控盘）；⑦是否可正常卖出（防貔貅/ honeypot）；⑧交易税是否合理（买卖税是否对称，卖出税>10%需警惕）；⑨Metadata 是否可变（防信息篡改）；⑩开发者钱包历史（是否流水发盘、Rug历史）。
Source: SolanaSniperBot.net / TokenToolHub / Beosin / De.Fi Scanner
URL: https://solanasniperbot.net/solana-token-scam-checklist/ / https://tokentoolhub.com/how-to-check-if-a-new-token-is-a-scam/ / https://beosin.com/resources/a-guide-to-avoiding-memecoin-related-scams / https://cryptolinks.com/3414/de-fi
Date: 2026-02-24 / 2025-11-10 / 2024-12-01 / 2026-05-12
Excerpt: "If it fails any one of these five checks, don't buy it." "Expect traps: honeypots, proxy upgrades, blacklists, hidden mints, and unlockable LPs." "Check if mint authority has been revoked... Check if freeze authority is active... Verify LP lock status and top holders."
Context: 多源安全工具和研究共同确认的检查清单，是交易前必做的风险控制。
Confidence: high

Claim: 手动扫链 vs 自动化扫链的效率对比：Bot 可在<400ms内检测并执行交易（同一块内），手动操作需15-60秒。Bot 可同时监控数百个钱包和多个代币，人类只能关注1-3个。Bot 消除情绪干扰，手动交易易受 FOMO 影响。但 Bot 的门槛在于：需要私钥托管风险（TG Bot 钱包私钥在服务器）、需要配置过滤参数、无法替代人类叙事判断。2026年顶级狙击 Bot 需要四层级基础设施：Yellowstone gRPC + 预构建交易模板 + Jito 多中继提交 + 裸机共置，才能在 Slot 0  landing。
Source: Uwuu.ai / RPC Fast / PumpPill / TelegramTrading.net
URL: https://uwuu.ai/blog/solana-trading-bot-vs-manual-trading / https://rpcfast.com/blog/how-to-launches-snipe-pump / https://www.pumppill.org/blog/solana-sniper-bot-guide-2026 / https://telegramtrading.net/pumpfun-sniper-bot/
Date: 2026-04-06 / 2026 / 2026-04-08 / 2026-04-10
Excerpt: "Sol trading bot: Detects and executes a trade in under 400ms. Manual trading: 15-60 seconds minimum." "Bots running this stack land in slot 0. Bots without it land in slot 2—and on Pump.fun, that gap is typically 20–60% of upside." "The entire cycle can run from 0 to peak to collapse in under 2 minutes. That is why manual traders almost never get real early entries anymore."
Context: 2026年竞争格局下，手动交易已处于结构性劣势，但完全依赖 Bot 需承担基础设施和安全风险。
Confidence: high

Claim: 2026年最新扫链趋势包括：①PumpSwap 全面取代 Raydium，迁移免费且即时，LP 自动销毁；②Anti-Sniper 基础设施成为标配（Bundled Launch Transactions、Locked LP at Graduation、Creator Authority Revocation）；③AI 狙击 Bot 普及（AI 评分、多信号聚合、自动执行）；④多链发射扩展（Base、BSC、Monad 等）；⑤公平发射机制演进（Bonding Curve Maturity Gates）；⑥流动性池启动和死亡周期缩短至15分钟以内，竞争窗口极度压缩。
Source: BlockEden / RPC Fast / OpenLiquid / Alchemii / Grenade
URL: https://blockeden.xyz/blog/2026/04/22/meme-launchpad-2-pump-fun-letsbonk-anti-sniper-bonding-curve-professionalization/ / https://rpcfast.com/blog/how-to-launches-snipe-pump / https://openliquid.io/blog/pumpfun-vs-pumpswap/ / https://www.alchemii.io/blog/what-is-pumpswap / https://grenade.tw/blog/gmgn-ai-tutorial/
Date: 2026-04-22 / 2026 / 2026-04-12 / 2026-05-24 / 2026-05-08
Excerpt: "The 2026 stack fights back on multiple fronts: Bundled launch transactions... Locked LP at graduation... Creator authority revocation." "Pump.fun generated more than $700M in fees during 2024–2025... only about 1 in every 100 tokens actually graduates." "2026年3月9日 — 内盘：在Pump.fun内盘寻找标的投资。需要花大量时间扫链，对体力、精力和坚持度要求高。"
Context: 2026年生态已高度专业化，反狙击和自动化成为基础设施级别的竞争要素。
Confidence: high

Claim: 成功抓到金狗的具体案例：①stupidmoney.sol 用$727买入 GOAT，4天后实现$2.24 million（约3,329x）；②匿名钱包 7fFCzx 用$54,000买入 PENGUIN，White House "Embrace the Penguin" 推文后获利$1.7 million；③幸运交易者用$16买入 PNUT，2周内实现$3 million（市值从<$10K到$2B+）。共同特征：极早期进入（内盘或刚开盘）、持有强叙事代币、耐心等待叙事发酵、分阶段止盈（DCA卖出）。
Source: Decrypt / CoinCrowd / Webopedia / CoinFomania / GitHub / Finbold
URL: https://decrypt.co/291739 / https://coincrowd.com/blogs/biggest-crypto-success-stories-of-2024 / https://www.webopedia.com/crypto/learn/memecoin-millionaires/ / https://coinfomania.com/crypto-trader-flips-727-into-2-4-million-in-four-days-how-did-this-happen/ / https://github.com/eltonaguiar/findtorontoevents_antigravity.ca/blob/main/meme_coin_degen_research.md / https://finbold.com/crypto-trader-turns-80k-into-2-million-in-6-days/
Date: 2024-11-14 / 2025-09-22 / 2026-05-20 / 2025-02-26 / 2024-10-17
Excerpt: "A lucky trader threw just $16.20 at a Solana meme coin only two weeks ago, letting it sit in their wallet for 10 days... pocketed a whopping $3 million." "stupidmoney.sol: Turned $727 into $2.24 million trading GOAT token." "The 60-Second Playbook: Phase 1 (0-15 seconds): Buy immediately with 20-30% slippage. Phase 2 (15-90 seconds): Hold if volume doubles every 10 seconds. Phase 3 (90+ seconds): Exit when Twitter influencers start shilling."
Context: 这些案例展示了极端回报的可能性，但幸存者偏差显著，同一钱包通常有极低的整体胜率（如7fFCzx 此前1,000+笔交易胜率<15%）。
Confidence: high

Claim: 不同时间窗口的扫链效果：1分钟窗口用于实时捕捉新创建代币和爆发性交易（>60笔/1min为安全信号），5分钟窗口用于确认趋势持续性（>600笔/5min），30分钟/1h/24h窗口用于筛选已外盘代币和聪明钱动向。对于中国时区交易者，Meme币交易高峰期对应美国交易时段（21:30-次日04:00 CST），流动性最高。周末流动性下降，价格波动更不可预测。
Source: BonkBot.io / ChartChampions / SGT Markets / PANews
URL: https://bonkbot.io/library/best-times-to-trade-crypto-meme-coins / https://chartchampions.com/the-best-time-to-trade/ / https://sgt.markets/the-best-times-to-trade-cryptocurrency-a-comprehensive-guide/ / https://www.panewslab.com/zh/articles/4eqt3xx6
Date: 2026-03-17 / 2026-03-24 / 2025-04-04 / 2024-11-22
Excerpt: "The best time to trade meme coins is during peak U.S. stock exchange trading hours... 9:30 AM to 4:00 PM Eastern Time." "For China: 9:30 PM – 4:00 AM (next day)." "Weekend liquidity lulls as people step back... reduced volume means lower liquidity, and also less predictable price movements." "1分钟内交易笔数超过60笔，或在5分钟内超过600笔，则说明该代币相对安全。"
Context: 时间窗口选择应结合策略类型（日内/波段）和时区优势，短线交易者应聚焦高流动性时段。
Confidence: high

Claim: 流动性迁移（内盘→外盘）的识别和时机：当 Bonding Curve 达到约85 SOL（约$69K市值）时，代币自动触发迁移到 PumpSwap。Bot 可通过监控 Yellowstone gRPC 的 bonding curve 完成事件（complete flag = true）在毫秒级捕获迁移。对人工交易者，GMGN "即将打满" 面板和 Bitquery 的 Bonding Curve Progress API 可用于提前识别接近毕业的代币。迁移瞬间通常是价格重新定价的关键窗口——早期 Bot 可在第一个 AMM Slot 买入，落后者则面对第一波零售买盘和较慢 Bot 的竞争。
Source: Bitquery / Shyft.to / RPC Fast / OpenLiquid / Nolimitnodes
URL: https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-Marketcap-Bonding-Curve-API/ / https://shyft.to/blog/how-to-stream-bonding-curve-transactions-on-pumpfun / https://rpcfast.com/blog/how-to-launches-snipe-pump / https://openliquid.io/blog/how-to-bundle-buy-pumpswap/ / https://nolimitnodes.com/products/pumpswap-data
Date: 2024-10-18 / 2026-01-22 / 2026 / 2026-01-17 / 2026-04-28
Excerpt: "BondingCurveProgress = 100 - ((leftTokens * 100) / initialRealTokenReserves)." "Bots that land their buy in that first AMM slot can be in at the floor. Bots that land one or two slots later are buying into the first wave of fast retail." "The boundary between the two stages is the most interesting moment in a memecoin's life."
Context: 迁移窗口是内盘扫链的终极时机，对基础设施要求极高，是专业交易者和业余玩家的分水岭。
Confidence: high

Claim: 开发者行为（Dev Behavior）和捆绑检测（Bundle Detection）是判断"开盘作恶"的关键。GMGN 将交易者分为开发者、老鼠仓、狙击者等类别，可标记疑似老鼠仓（用小号钱包分散持仓试图砸盘跑路）。MemeRadar 插件可展示 DEV 历史发盘数据，快速规避流水发盘 DEV。如果开发者通过捆绑交易在单一原子交易中用多个钱包买入大量代币，或持仓>5%，应视为高风险信号。2026年反狙击基础设施（Bundled Launch）的兴起使得部分捆绑行为可能是创作者的防御性操作，需结合其他指标综合判断。
Source: GMGN 教程 / MemeRadar / BlockEden / PANews
URL: https://www.panewslab.com/zh/articles/wxotn8i4 / https://www.offidocs.com/index.php/chromium-web-store/1742164-memeradar-extension / https://blockeden.xyz/blog/2026/04/22/meme-launchpad-2-pump-fun-letsbonk-anti-sniper-bonding-curve-professionalization/ / https://www.panewslab.com/zh/articles/4eqt3xx6
Date: 2024-11-20 / 2026 / 2026-04-22 / 2024-11-22
Excerpt: "标记疑似老鼠仓，判断庄家是否想用小号钱包分散代币试图砸盘跑路。" "Bundled launch transactions... let creators launch a token and execute initial buys across four wallets within a single atomic transaction." "Avoid tokens where creators hold >5% of supply."
Context: 开发者行为分析是内盘扫链的"人性层"判断，技术工具和链上分析结合才能有效识别。
Confidence: high

Claim: GMGN 的 Telegram Bot 和自动交易功能可显著提升执行速度，但存在私钥托管风险。Bot 钱包私钥存放于服务器，建议不要存放大量资金，赚到钱后尽早转回个人钱包。自动狙击功能支持设置：每笔买入SOL金额、池子最低值、市值最高值、持有人最大值、5分钟交易额/交易数阈值、自动止盈止损（按百分比）。建议单币种投入<总资产2%，Meme币总配置<10%。
Source: PANews / Cryptowesearch / Grenade / AIHelper
URL: https://www.panewslab.com/zh/articles/4eqt3xx6 / https://cryptowesearch.com/articles/on-chain-super-tool-gmgn-ai-intro / https://grenade.tw/blog/gmgn-ai-tutorial/ / https://aihelper.blog/2025/06/19/gmgn-ai%E5%A6%82%E4%BD%95%E8%87%AA%E5%8A%A8%E5%81%9A%E5%B8%82/
Date: 2024-11-22 / 2024-12-16 / 2026-05-08 / 2025-06-19
Excerpt: "所有Telegram bot都面临私钥是服务器托管的问题，GMGN Bot也不例外，所以尽量不要放太多子弹在Bot里，赚到钱可以尽早转到交易所或者自己的链上钱包。" "单币种投入<2%（如1万美元本金，单币最多200美元）。" "滑点：日常设0.5%，热门盘可调至5-10%。启用'防夹模式'阻挡MEV攻击。"
Context: 自动化交易的风险收益平衡和资金管理纪律是可持续参与的前提。
Confidence: high

Claim: 慢雾余弦于2025年10月披露，GMGN 相关被盗情报的共性是：用户私钥未泄露，但 SOL/BNB 被买入貔貅盘，黑客通过貔貅盘撤池方式卷走用户资金。这提示即使使用看似安全的工具，仍需自主执行合约安全检查，不可完全依赖平台提示。
Source: ChainCatcher
URL: https://www.chaincatcher.com/zh-tw/article/2215729
Date: 2025-10-28
Excerpt: "慢雾余弦在X平台发文表示：'看了下提交给我们的几十条与GMGN有关的被盗情报，共性：用户的私钥没有泄露，但SOL BNB都被买入了貔貅...'"
Context: 安全事件警示：工具便利不等于安全，貔貅盘和恶意合约是持续威胁。
Confidence: high

Claim: 针对内盘扫链的筛选参数，社区共识推荐：至少一个社交媒体、DEV已清算（或持仓<5%）、持有者≥40（外盘≥1000为佳）、交易数>100（或1min>60/5min>600）、外盘市值>100k。已外盘的代币风险相对较低，新手建议优先从"已开盘"开始练习。快捷买入建议预设SOL数量（如0.05-0.5 SOL），滑点0.5%-2%（内盘紧急时可15-30%），开启防夹模式（Anti-MEV），优先费0.002-0.006 SOL。
Source: 加密头条 / GMGN Gitbook / Grenade / 夜雨聆风
URL: https://2jmtt.com/newbie/2501/202501248635.html / https://gmgnai.gitbook.io/cn/gen-dan-xin-hao-pump-cto-xin-hao-zi-dong-gen-dan / https://grenade.tw/blog/gmgn-ai-tutorial/ / https://www.yeyulingfeng.com/226705.html
Date: 2025-01-24 / 2024-09-04 / 2026-05-08 / 2025-08-12
Excerpt: "新手建议从'已开盘'的代币开始练习...建议每一栏把'至少有一个社交媒体'勾选上。" "设置滑点并启用防夹模式模式...滑点一般建议0.5%左右，着急买入可调15-30%。" "买入优先费：设置每笔跟单的gas费(包含优先费)。买入滑点：设置每笔跟单买入的滑点值。"
Context: 参数设置是扫链效率的关键，不同风险偏好对应不同参数组合。
Confidence: high

Claim: 筹码结构的健康标准：Top10 持仓15%-25%为健康，25%-35%为亚健康，35%以上不健康。持有人数1000地址以上为佳。流动性池建议100 SOL以上（外盘），内盘几十SOL也可参与但风险高。老鼠仓比例应<20%，理想为0。狙击者（Sniper）大量快速介入且池子浅时，90%概率导致价格暴跌。
Source: 币币情 / BlockBeat / PANews / Odaily
URL: https://www.68bbq.com/news/detail/96050 / https://blockbeat.hashnode.dev/2025meme / https://www.panewslab.com/en/articles/4eqt3xx6 / https://www.odaily.news/en/post/5199963
Date: 2025-03-18 / 2025-07-01 / 2024-11-22 / 2024-11-22
Excerpt: "Top10持仓：15%-25%健康，25%-35%亚健康，35%以上不健康。" "老鼠仓比例不超过20%。如果完全没有老鼠仓，通常是更理想的情况。" "如果在开盘时有大户迅速介入，而流动性池的深度较浅，这种情况下有90%的可能性会导致价格暴跌。"
Context: 筹码结构分析是判断代币能否持续上涨而非被控盘砸盘的核心依据。
Confidence: high

Claim: 2026年 GMGN 新功能包括：Fourmeme Agent 代币支持（BSC链）、Base 链 AI 信号推送（KOL钱包净流入、K线图新增捆绑交易数据）、Monad 链支持、EVM 链风险警告自动提示。GMGN OpenAPI Skills 支持 AI Agent 实时扫链、多链趋势排名、代币安全评分（Rug ratio 0-1）、智能钱包分析、自动交易（端到端延迟<0.3秒）。
Source: GMGN Skills GitHub / Grenade
URL: https://github.com/GMGNAI/gmgn-skills / https://grenade.tw/blog/gmgn-ai-tutorial/
Date: 2026 / 2026-05-08
Excerpt: "Real-time chain scanning... Token analytics: Security check: open source, renounced, honeypot, wash trading, Rug ratio score. Automated trading: end-to-end latency under 0.3 seconds." "2026年GMGN新功能：Fourmeme Agent代币...Base链AI信号推送...Monad链支援...EVM链风险警告。"
Context: GMGN 正在向 AI 原生和全链覆盖演进，工具能力持续扩展。
Confidence: high

Claim: 金狗发现的退出策略同样关键。社区共识推荐：30-30-40 法则（30%在3x卖出，30%在5x卖出，留40%博更高）；翻倍出本+梯度减仓；阶梯止盈（25% at 2x, 25% at 5x, 25% at 10x, 25% hold）；15% 移动止损锁定利润。当交易量飙升但价格不跟进（Volume-Based Exit）、Twitter KOL 开始大规模喊单（叙事极点）时，应考虑退出。
Source: GitHub Degen Research / CoinCrowd / Beosin
URL: https://github.com/eltonaguiar/findtorontoevents_antigravity.ca/blob/main/meme_coin_degen_research.md / https://coincrowd.com/blogs/biggest-crypto-success-stories-of-2024 / https://beosin.com/resources/a-guide-to-avoiding-memecoin-related-scams
Date: 2024-2025 / 2025-09-22 / 2024-12-01
Excerpt: "30-30-40 Rule: Sell 30% at 3x, 30% at 5x, leave 40% for moonshots. Trailing Stop-Loss: Set 15% trailing stop to lock in profits. Volume-Based Exits: Exit when volume spikes without price follow-through." "当社区FOMO到极点时，及时退出。"
Context: 金狗发现不仅是"买入"，更核心的是"在何时以何种方式退出"。
Confidence: high

---

### References

[^1]: https://grenade.tw/blog/gmgn-ai-tutorial/ (2026-05-08)
[^2]: https://yibi123.com/solana%E5%9C%9F%E7%8B%97%E5%B8%81%E6%96%B0%E6%89%8B%E5%85%A5%E9%97%A8%E6%95%99%E7%A8%8B%EF%BC%9A%E7%94%A8gmgn%E6%89%AB%E9%93%BE%E6%89%BE%E5%88%B0%E7%99%BE%E5%80%8D%E5%B8%81/ (2025-01-24)
[^3]: https://paragraph.com/@fomoplz/AtDIy0kS6zj55LYqzmpq (2024-11-22)
[^4]: https://www.panewslab.com/zh/articles/wxotn8i4 (2024-11-20)
[^5]: https://www.odaily.news/en/post/5199963 (2024-11-22)
[^6]: https://www.chaincatcher.com/en/article/2153149 (2024-11-21)
[^7]: https://github.com/GMGNAI/gmgn-skills (2026)
[^8]: https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-Marketcap-Bonding-Curve-API/ (2024-10-18)
[^9]: https://shyft.to/blog/how-to-stream-bonding-curve-transactions-on-pumpfun (2026-01-22)
[^10]: https://mp.weixin.qq.com/s/xVGRoKZf_3JcuexfsQs20g (貔貅识别)
[^11]: https://www.chaincatcher.com/zh-tw/article/2215729 (2025-10-28)
[^12]: https://www.panewslab.com/en/articles/4eqt3xx6 (2024-11-22)
[^13]: https://github.com/eltonaguiar/findtorontoevents_antigravity.ca/blob/main/meme_coin_degen_research.md (Meme Degen Research)
[^14]: https://blockeden.xyz/blog/2026/04/22/meme-launchpad-2-pump-fun-letsbonk-anti-sniper-bonding-curve-professionalization/ (2026-04-22)
[^15]: https://rpcfast.com/blog/how-to-launches-snipe-pump (2026)
[^16]: https://reapersniper.io/blog/how-to-snipe-memecoins-solana-pumpfun (2026-04-02)
[^17]: https://openliquid.io/blog/pumpfun-vs-pumpswap/ (2026-04-12)
[^18]: https://www.alchemii.io/blog/what-is-pumpswap (2026-05-24)
[^19]: https://nolimitnodes.com/products/pumpswap-data (2026-04-28)
[^20]: https://2jmtt.com/newbie/2501/202501248635.html (2025-01-24)
[^21]: https://news.qq.com/rain/a/20241209A01VWC00 (2024-12-09)
[^22]: https://www.offidocs.com/index.php/chromium-web-store/1742164-memeradar-extension (MemeRadar)
[^23]: https://uwuu.ai/blog/solana-trading-bot-vs-manual-trading (2026-04-06)
[^24]: https://www.pumppill.org/blog/solana-sniper-bot-guide-2026 (2026-04-08)
[^25]: https://telegramtrading.net/pumpfun-sniper-bot/ (2026-04-10)
[^26]: https://cryptonews.com/cryptocurrency/best-solana-sniper-bots/ (2026-01-30)
[^27]: https://www.quicknode.com/builders-guide/best/top-10-solana-sniper-bots (2026)
[^28]: https://bitsgap.com/blog/manual-trading-vs-crypto-trading-bots-when-automation-actually-makes-sense (2026-05-28)
[^29]: https://dysnix.com/blog/top-solana-sniper-bot (2026-02-02)
[^30]: https://www.panewslab.com/zh/articles/4eqt3xx6 (2024-11-22) [进阶篇]
[^31]: https://cryptowesearch.com/articles/on-chain-super-tool-gmgn-ai-intro (2024-12-16)
[^32]: https://solanasniperbot.net/solana-token-scam-checklist/ (2026-02-24)
[^33]: https://tokentoolhub.com/how-to-check-if-a-new-token-is-a-scam/ (2025-11-10)
[^34]: https://beosin.com/resources/a-guide-to-avoiding-memecoin-related-scams (2024-12-01)
[^35]: https://cryptolinks.com/3414/de-fi (2026-05-12)
[^36]: https://cryptolinks.com/lp-security (2026-06-26)
[^37]: https://apespace.io/honeypot/0x168c01854ea985f38de3c64dab4aaeb76c6fdc35 (Honeypot Checker)
[^38]: https://www.xtycwlkj.com/news/lanmu1/3242.html (2025-08-21)
[^39]: https://decrypt.co/291739/lucky-trader-16-3-million-pnut-meme-coin (2024-11-14)
[^40]: https://coincrowd.com/blogs/biggest-crypto-success-stories-of-2024 (2025-09-22)
[^41]: https://www.webopedia.com/crypto/learn/memecoin-millionaires/ (2026-05-20)
[^42]: https://coinfomania.com/crypto-trader-flips-727-into-2-4-million-in-four-days-how-did-this-happen/ (2025-02-26)
[^43]: https://finbold.com/crypto-trader-turns-80k-into-2-million-in-6-days/ (2024-10-17)
[^44]: https://bonkbot.io/library/best-times-to-trade-crypto-meme-coins (2026-03-17)
[^45]: https://chartchampions.com/the-best-time-to-trade/ (2026-03-24)
[^46]: https://sgt.markets/the-best-times-to-trade-cryptocurrency-a-comprehensive-guide/ (2025-04-04)
[^47]: https://bullrank.io/learn/raydium-migration-pump-fun-graduation (2026-03-01)
[^48]: https://bullrank.io/learn/how-bonding-curves-work (2026-02-28)
[^49]: https://finance.sina.com.cn/blockchain/roll/2025-06-07/doc-inezfyqx9435744.shtml (2025-06-07)
[^50]: https://news.qq.com/rain/a/20250513A05DZP00 (2025-05-13)
[^51]: https://openliquid.io/blog/how-to-bundle-buy-pumpswap/ (2026-01-17)
[^52]: https://www.yeyulingfeng.com/226705.html (2025-08-12)
[^53]: https://www.coinglass.com/zh/news/244241 (2025-06-24)
[^54]: https://www.aicoin.com/zh-Hans/article/430067 (2024-11-20)
[^55]: https://www.68bbq.com/news/detail/96050 (2025-03-18)
[^56]: https://blockbeat.hashnode.dev/2025meme (2025-07-01)
[^57]: https://www.jb51.net/blockchain/949547.html (2024-08-22)
[^58]: https://www.oeexchange.com/detail/299.html (2024-08-09)
