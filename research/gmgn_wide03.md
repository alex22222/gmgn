## Facet: 扫链与金狗发现策略

### Key Findings

- **GMGN扫链核心操作流程**：通过Meme页面监控Pump.fun新创建、即将满盘、已外盘三种状态代币，使用内置筛选器勾选"至少一个社交媒体"和"DEV已清算"排除基础诈骗；即将满盘代币要求持有者≥40、交易数>100，已外盘代币筛选市值>100k以排除开盘即割项目[^1]。

- **快捷买入与参数设置**：GMGN页面右上角⚡️快捷购买按钮支持一键买入，用户可预设每次购买SOL数量；滑点建议0.5%-2%，剧烈波动时可提高到10%；必须开启防夹模式（Anti-MEV）防止三明治攻击[^2]。Telegram Bot自动买入支持设置每笔SOL数量、池子最低金额（如2000 USD）、市值最大限制（如200000 USD）[^3]。

- **止盈止损配置**：GMGN支持自动卖预设，止损单填写负百分比（如-30%），止盈单填写正百分比（如+30%），建议所有卖出数量加起来等于100%；CLI提供`cooking`一键策略单，买入同时自动挂止盈+止损条件单，例如`--condition-orders '[{"order_type":"profit_stop","side":"sell","price_scale":"100","sell_ratio":"100"},{"order_type":"loss_stop","side":"sell","price_scale":"50","sell_ratio":"100"}]'`[^4]。

- **内盘扫链策略**：Pump.fun内盘（市值<$69K）风险最高，代币在此阶段极易死亡；当市值接近$69K-$100K时流动性自动迁移到Raydium（外盘），迁移需10-30分钟。内盘筛选重点：DEV已清算、持有者数量、交易活跃度。新币页面额外提供Mint权限丢弃、黑名单、烧池筛选，勾选"过滤风险"自动启用[^1]。

- **外盘一段介入与退出**：外盘一段是内盘迁移后价格快速波动阶段，需"快、狠、准"判断市值与盈亏比，早期（几十万美元市值）介入最佳，超过千万市值追高易被套[^2][^5]。

- **外盘二段策略**：在PVP结束、价格下跌50%-80%时寻找有价值资产买入，需较强投研能力。实盘案例$AVA：2000万附近陆续买入，平均成本1700万，1200万时浮亏30%+坚持不止损，最终涨至3亿。选择依据：热门PVP标的背景、团队实力、叙事/产品方向可靠。建仓建议大资金耐心操作，可持续几天慢慢建仓；止盈采用陆续卖出，止损不设特别明确亏损线，基本面未变则不止损[^5][^6]。

- **金狗发现核心指标**：（1）流动性池≥100 SOL（小池子易被大户砸盘）；（2）真实交易笔数：1分钟>60笔或5分钟>600笔；（3）Mint权限已丢弃；（4）黑名单：否；（5）烧池比例100%（未烧池约60%概率Rug）；（6）Top10持仓<30%；（7）老鼠仓比例<20%；（8）DEXScreener已付费（表明团队或社区运营）[^7]。

- **叙事判断与社区热度评估**：好叙事=新叙事+新大V发币+新梗+开盘不作恶+不搞捆绑。评估流程：5分钟热度榜锁定异动→推特搜索合约地址（监测叙事完整性、KOL互动密度）→结合开发者持仓比例及社交媒体活跃度综合研判。GMGN KOL/VC监控、DeBot AI信号、chain.fm KOL频道建立影响力矩阵，关注"高粉丝粘性+叙事能力+实盘验证"的KOL[^8]。

- **合约安全与貔貅识别**：慢雾创始人余弦指出GMGN、DEXTools、DEX Screener等平台存在大量隐蔽貔貅项目，部分恶意代码常规安全工具无法检测，建议将合约代码提交给Claude/GPT等AI分析[^9]。GoPlus已第一时间支持貔貅风险特征检测并推送至GMGN等合作平台。关键检查项：放弃mint权限、放弃合约控制权、销毁流动性池、Top10持仓占比。貔貅升级版本增加滑点功能，通过tokensForLiquidity变量自动触发，常规检测工具可能无法识别[^10]。

- **时间窗口扫链效果**：GMGN支持1分钟/5分钟/30分钟/1小时/24小时多时间窗口筛选。5分钟热度榜用于锁定异动项目；1分钟交易笔数>60笔、5分钟>600笔是安全信号。金狗出现频率具有时间规律：晚上9点后从2%跳到4%，凌晨3-6点达峰值，上午回落到2%-3%[^1][^11]。

- **手动vs自动扫链效率**：手动扫链（GMGN网页、Bullx）在三个方面比拼速度：发现新币、发现聪明钱动向、最终买入卖出。但2026年流动性池启动和死亡周期缩短至15分钟，人类5秒加载+5秒确认已错过窗口。自动化扫链通过PumpPortal WebSocket→Node.js listener→AI评估→自动执行，10秒信号评估窗口，支持多层级利润阶梯退出。Telegram Bot更快但安全风险更高，建议只存少量资金[^12][^13]。

- **2026年最新趋势**：（1）Pump.fun迁移至自有DEX PumpSwap而非Raydium；（2）AI Meme币狙击工具兴起（MoonPay pump-fun-sniper skill）；（3）跨链发射平台扩展（BNBpump.fun等）；（4）公平发射模式取代预售和私募，LP自动销毁；（5）手动交易在2026年难以成功，自动化+Jito Bundles成为标配；（6）多链流动性桥接与111交易所同步上市策略出现[^13][^14]。

### Major Players & Sources

- **GMGN**：Meme币交易、扫链和链上数据分析头部工具，支持Solana/Tron/Base/Ethereum/Blast，提供网页端+Telegram Bot+CLI三种交易方式，内置500+数据分析维度[^15]。

- **Odaily/星球日报**：发布"从入门到抓金狗"系列教程，由Golem(@web3_golem)撰写，系统讲解GMGN扫链全流程，华语区核心教育内容源[^1]。

- **PanewsLab**：发布GMGN"打狗"进阶教程（入门+进阶两篇），详细拆解指标筛选、Telegram Bot自动交易、限价挂单，华语区实战教程标杆[^3][^7]。

- **Grenade.tw**：发布GMGN完整教学2026系列，涵盖扫链、热门代币、手续费、链上打法四段论，持续更新[^2][^5]。

- **慢雾(SlowMist)**：安全公司，创始人余弦率先曝光GMGN等平台隐蔽貔貅风险，推动GoPlus安全API升级[^9]。

- **MoonPay**：2026年推出Pump.fun AI狙击工具（pump-fun-sniper skill），通过Claude+PumpPortal WebSocket实现自动化信号评估与交易执行[^13]。

- **Meme Insider**：发布《从0到1000万美金MEME操作指南》，详细拆解外盘二段与准上所资产打法，含$AVA实盘案例[^6]。

- **安然**：华语Meme币资深玩家，通过AMA分享扫链方法论，强调"学习识别垃圾盘特征，扫链教程可帮助筛选70-80%垃圾项目"[^8]。

- **Photon/Bullx/MevX/Banana Gun**：GMGN竞品/互补工具，Photon提供Memescope实时feed和Quick Buy，Bullx支持New Pairs 2分钟内新币，Banana Gun专注狙击[^12]。

- **GoPlus**：安全API提供商，已支持貔貅特征检测并覆盖GMGN、DEXScreener、DEXTools等平台[^10]。

### Trends & Signals

- **AI+自动化扫链成为2026年主流**：从手动网页扫链→Telegram Bot→CLI→AI Agent全自动化，交易窗口从分钟级压缩到秒级，MoonPay等将AI评估与链上执行深度整合[^13]。

- **Pump.fun生态迁移**：2025-2026年Pump.fun从依赖Raydium迁移至自有DEX PumpSwap，对扫链工具的监听逻辑和迁移判断产生重大影响，需要重新适配[^14]。

- **公平发射模式普及**：预售和私募模式被bonding curve+自动LP销毁取代，降低Rug风险但同时也压缩了早期套利空间，内盘竞争更激烈[^14]。

- **多链Meme发射平台兴起**：BNBpump.fun、Four.Meme等跨链平台崛起，Solana垄断地位被打破，扫链范围从单链扩展到多链监控[^14]。

- **安全攻防升级**：貔貅合约从简单黑名单升级到滑点伪装+变量自动触发，传统检测工具失效，AI代码分析和实时行为监控成为新防线[^10]。

- **时间规律被发现**：金狗出现频率存在显著时间分布（UTC晚间-凌晨高峰），扫链效率可通过时间窗口优化提升[^1]。

- **从PVP到投研的打法分层**：外盘二段和准上所资产需要团队化投研能力（团队评估、叙事方向、产品技术、筹码分析、市值空间），散户与机构能力差距拉大[^6]。

### Controversies & Conflicting Claims

- **智能钱是否值得跟单**：一派认为跟单聪明钱可快速获利（GMGN支持10地址跟单+自动跟卖），另一派认为"聪明钱有时并不聪明"——小资金频繁操作、早期入场早期退出，主要利润靠偶然抓到金狗，盲目跟单可能因资金量小跟不上频率，甚至因跟单被杀而亏损本金[^1]。

- **Telegram Bot安全性争议**：TG Bot交易速度更快，但"更容易被黑客盗取资金"，与便捷性之间存在根本权衡；慢雾等安全机构建议只在Bot钱包中存入少量资金[^3][^12]。

- **内盘vs外盘风险认知**：部分玩家认为外盘"风险已降低"适合新手，但另有观点指出"进入外盘不意味着100%上涨，存在大量开盘即归零案例"，外盘只是"相对"内盘风险低，绝对风险仍然很高[^2]。

- **手动vs自动的边界**：2026年有声音认为"手动交易完全失败"，但也有人认为自动化在带来速度的同时引入了新的系统性风险（API故障、信号误判、闪电崩盘），手动判断在关键决策节点仍不可替代[^13]。

- **GMGN平台信任风波**：2025年1月TRUMP币发行期间，GMGN老板持有大量资金但未跑路，社区出现"不跑路就是信任"的争议性讨论，折射出链上工具的信任建立高度依赖创始人行为而非制度保障[^15]。

- **Pump.fun是"吸血鬼"争议**：有观点认为Pump.fun给Solana造成更多抛压，引导用户疯狂砸盘，吸链上血，其潜在IPO设计与交易所预售压力引发社区对其贪婪性质的批评[^16]。

### Recommended Deep-Dive Areas

- **AI自动化扫链系统架构**：MoonPay的Pump.fun AI狙击工具（pump-fun-sniper skill）提供了一套从PumpPortal WebSocket实时监听→10秒信号评估→自动执行→多层级退出的完整架构，值得深入研究其信号评估阈值和退出规则设计[^13]。

- **貔貅合约的进化与防御**：从简单黑名单到隐藏变量自动触发的新一代貔貅合约，需要结合AI代码分析、链上行为监控、实时流动性检测多层防御体系，单独依赖传统安全API已不足[^10]。

- **外盘二段的投研框架**：$AVA案例展示了团队评估、叙事验证、筹码分析、市值空间测算的完整框架，但华语区系统性的投研方法论仍较稀缺，需要更多实盘案例积累[^6]。

- **多链扫链工具整合**：随着BNBpump.fun、Base、Blast等链上Meme发射平台兴起，单一Solana工具链已不够用，需要研究跨链信号聚合和自动化执行方案[^14]。

- **Jito Bundles与MEV防护**：2026年Solana Meme交易的关键基础设施，理解Jito Bundle优先级机制、Anti-MEV Bot原理、以及bribe费用优化，是自动化扫链成功率的决定性因素[^13]。

- **KOL影响力矩阵的量化构建**：MemeRadar等工具已能追踪400+KOL的买入/持仓和TG群喊单，但如何量化"叙事能力"和"粉丝粘性"，建立可复用的Alpha信号评分体系，仍是一个开放问题[^8]。

- **时间窗口优化与生物钟管理**：金狗出现频率存在UTC晚间-凌晨峰值，但华语区交易者生物钟与此冲突，需要研究如何在不牺牲健康的前提下通过自动化+时间窗口策略捕获峰值机会[^1]。

---

## 引用列表

[^1]: Odaily Planet Daily, Golem (@web3_golem). "From getting started to catching the golden dog, how can Meme novices use GMGN to sweep the chain?" November 27, 2024. https://www.odaily.news/en/post/5200046

[^2]: Grenade.tw. "GMGN 完整教學2026｜聰明錢跟單、手續費、下載與風險整理." March 9, 2025 / May 8, 2026. https://grenade.tw/blog/gmgn-ai-tutorial/

[^3]: PanewsLab. "GMGN'打狗'进阶教程：选币及自动交易." November 22, 2024. https://www.panewslab.com/zh/articles/4eqt3xx6

[^4]: GMGN AI GitHub. "gmgn-skills/Readme.zh.md." https://github.com/GMGNAI/gmgn-skills/blob/main/Readme.zh.md

[^5]: Grenade.tw. "流動性飆升，詳解GMGN 如何帶你在爆炸行情賺數百萬美元." January 25, 2025. https://grenade.tw/blog/gmgn-solana/

[^6]: Meme Insider. "从0到1000万美金MEME操作指南." February 2, 2025. https://meme-insider.com/zh-cn/article/the-meme-playbook-from-0-to-10-million/

[^7]: PanewsLab. "GMGN'打狗'进阶教程：选币及自动交易（指标筛选部分）." November 22, 2024. https://www.panewslab.com/zh/articles/4eqt3xx6

[^8]: PanewsLab. "从萌宠形象到总统IP，一文读懂MEME币的前世今生." March 20, 2025. https://www.panewslab.com/news/articledetails/mpqv73xdabd6.html ; 安然AMA. https://www.panewslab.com/zh/sqarticledetails/um7wahrt.html

[^9]: TechFlame. "慢雾创始人：GMGN等平台存在大量隐蔽的'貔貅'项目，建议用AI识别风险." September 25, 2024. https://www.techflame.com/article/dGVjaC1mbGFtZS0xNTQ0Ny0y

[^10]: BlockBeats. "余弦：GoPlus已支持相关'貔貅'的特征检测，并覆盖GMGN、DEXScreener等平台." September 25, 2024. https://www.theblockbeats.info/flash/264818 ; 支点CTO. "BSC链上几种貔貅币的实现方式分析以及怎么快速识别貔貅币." June 12, 2025.

[^11]: Followin.io. "把握下一個千倍幣，Meme玩家必備掃鏈工具指南." https://followin.io/zh-Hant/feed/14567695

[^12]: 新浪区块链. "Meme猎手进阶教学：超有用的工具及方法论." August 9, 2024. https://finance.sina.com.cn/blockchain/2024-08-09/doc-inchzawq5938147.shtml

[^13]: MoonPay Support. "Automating the Pump.fun hunt: A guide to the AI memecoin sniper." May 16, 2026. https://support.moonpay.com/en/articles/629129-automating-the-pump-fun-hunt-a-guide-to-the-ai-memecoin-sniper ; AI-FRB. "Solana Meme Coin Trading Strategy: Risk, Liquidity & Timing (2026)." May 10, 2026. https://ai-frb.com/blog/ultimate-solana-meme-coin-strategy

[^14]: ChainCatcher/播客. "#14：美股是压死币圈的最后一根稻草？随便侃侃婚恋小课堂." June 20, 2025. https://www.xiaoyuzhoufm.com/episode/685512c52a38b4d979e2caf0 ; Tapbit Blog. "How to Create a Meme Coin on Solana in 2025–2026." January 12, 2026. https://blog.tapbit.com/how-to-create-a-meme-coin-on-solana-in-2025-2026-step-by-step-guide-pump-fun-raydium/ ; Nerdbot. "Top BNB Chain Meme Coin Launchpads to Watch in 2026." February 17, 2026. https://nerdbot.com/2026/02/17/top-bnb-chain-meme-coin-launchpads-to-watch-in-2026/

[^15]: QuickNode. "GMGN.AI." October 7, 2024. https://www.quicknode.com/builders-guide/tools/gmgn-ai-by-gmgn-ai-team ; 小宇宙播客. "#9：川普发币，剑开天门！半场开香槟复盘." January 18, 2025. https://www.xiaoyuzhoufm.com/episode/67e0dcb4dd11f9c8c1ae7b3d

[^16]: 小宇宙播客. "#14：美股是压死币圈的最后一根稻草？" June 20, 2025. https://www.xiaoyuzhoufm.com/episode/685512c52a38b4d979e2caf0
