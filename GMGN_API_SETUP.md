# GMGN 系统配置
# 生成时间: 2026-07-03

## 密钥对信息

私钥文件: ~/.config/gmgn/keypair.pem
公钥 (Public Key):
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAis/8B3HcVoq49KAf0MM+zT55eH2T+oiN9/Z2DR1KGAk=
-----END PUBLIC KEY-----

## 获取 GMGN API Key 步骤

### 第 1 步: 访问 GMGN 开发者链接

点击以下链接 (已自动嵌入你的公钥):

https://gmgn.ai/ai/generateapi?pbk=-----BEGIN%20PUBLIC%20KEY-----%0AMCowBQYDK2VwAyEAis%2F8B3HcVoq49KAf0MM%2BzT55eH2T%2BoiN9%2FZ2DR1KGAk%3D%0A-----END%20PUBLIC%20KEY-----%0A

或者: 打开 https://gmgn.ai/ai/generateapi 并粘贴上方公钥

### 第 2 步: 登录 GMGN 账户

1. 使用你的钱包登录 GMGN (Phantom / OKX / Trust Wallet 等)
2. 确认公钥绑定
3. 系统将生成 API Key

### 第 3 步: 配置 API Key

获取到 API Key 后，选择以下任一方式配置:

**方式 1 - 环境变量 (推荐)**:
```bash
export GMGN_API_KEY="your_api_key_here"
```

**方式 2 - 项目配置文件**:
```bash
cd /Users/henry/projects/gmgn
mkdir -p ~/.config/gmgn
echo '{"gmgn_api_key": "your_api_key_here"}' > ~/.config/gmgn/config.json
```

**方式 3 - 项目 .env 文件**:
```bash
cd /Users/henry/projects/gmgn
echo 'GMGN_API_KEY="your_api_key_here"' > .env
```

### 第 4 步: 验证连接

```bash
cd /Users/henry/projects/gmgn
python3 -c "
from gmgn_monitor import ConfigManager, GmgnApiClient
import os

config = ConfigManager()
keys = config.validate_api_keys()
print(f'GMGN API Key 可用: {keys.get(\"gmgn_api_key\", False)}')

if keys.get('gmgn_api_key'):
    client = GmgnApiClient(api_key=os.environ.get('GMGN_API_KEY'))
    data = client.get_smartmoney(chain='sol', limit=5)
    print(f'✅ 连接成功，获取到 {len(data)} 条 Smart Money 数据')
else:
    print('❌ API Key 未配置')
"
```

## 注意事项

- 私钥文件 `~/.config/gmgn/keypair.pem` 包含签名密钥，**不要泄露**
- API Key 与你的 GMGN 账户绑定，有调用频率限制
- 公钥已自动嵌入链接，无需手动复制

## 链接 (短格式)

如果上方长链接无法打开，使用此短链接:
https://gmgn.ai/ai/generateapi?pbk=MCowBQYDK2VwAyEAis%2F8B3HcVoq49KAf0MM%2BzT55eH2T%2BoiN9%2FZ2DR1KGAk%3D
