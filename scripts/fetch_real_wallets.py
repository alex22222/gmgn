import json, os, sys
sys.path.insert(0, '.')
from gmgn_monitor.gmgn_api_client import GmgnApiClient
from gmgn_monitor.wallet_scorer import score_wallet
from gmgn_monitor.wallet_filter import filter_wallet, WalletFeatures, FilterThresholds

API_KEY = os.getenv('GMGN_API_KEY')
if not API_KEY:
    raise ValueError('GMGN_API_KEY environment variable is required')

client = GmgnApiClient(API_KEY)

# 1. Fetch smart money transactions (get unique wallets)
print('正在获取 Smart Money 交易数据...')
data = client.get_smartmoney('sol', 100)
wallets = {}  # address -> {tags, trades, volume}

if isinstance(data, dict) and 'list' in data:
    for item in data['list']:
        addr = item.get('maker', '')
        if not addr:
            continue
        tags = item.get('maker_info', {}).get('tags', [])
        amount_usd = item.get('amount_usd', 0)
        side = item.get('side', '')

        if addr not in wallets:
            wallets[addr] = {'tags': set(tags), 'trades': 0, 'volume': 0.0}
        wallets[addr]['trades'] += 1
        wallets[addr]['volume'] += amount_usd
        wallets[addr]['tags'].update(tags)

print(f'从 {len(data.get("list", []))} 笔交易中提取出 {len(wallets)} 个唯一钱包')
print()

# 2. Show top wallets by volume
print('=== 按交易量排序的前 10 个钱包 ===')
sorted_wallets = sorted(wallets.items(), key=lambda x: x[1]['volume'], reverse=True)
for i, (addr, info) in enumerate(sorted_wallets[:10]):
    tags = ', '.join(info['tags'])
    print(f'  {i+1}. {addr[:30]}...')
    print(f'     交易数: {info["trades"]}, 交易量: ${info["volume"]:.2f}, 标签: {tags}')

print()
# 3. Try to get wallet stats for top wallet (API limits may apply)
if sorted_wallets:
    top_addr = sorted_wallets[0][0]
    print(f'=== 尝试获取 top 钱包 {top_addr[:20]}... 的详细 stats ===')
    try:
        stats = client.get_wallet_stats('sol', [top_addr], '7d')
        print(f'  Stats: {json.dumps(stats, indent=2)[:1000]}')
    except Exception as e:
        print(f'  无法获取 stats: {e}')
        
# 4. Save candidate wallets to file
output = []
for addr, info in sorted_wallets:
    output.append({
        'address': addr,
        'trades': info['trades'],
        'volume_usd': round(info['volume'], 2),
        'tags': list(info['tags']),
        'source': 'gmgn_smartmoney',
    })

with open('data/candidate_wallets_smartmoney.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f'\n已保存 {len(output)} 个候选钱包到 data/candidate_wallets_smartmoney.json')
