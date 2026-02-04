# Stock Data Pipeline - R2 Storage Documentation

本ドキュメントは、Stock Data Pipeline が生成する R2 ストレージのデータ構造と利用方法を説明します。

---

## 📁 フォルダ構造
```
r2://your-bucket/
├── stocks/
│   ├── daily/
│   │   ├── core/              # 価格データ + RS/RRS スコア
│   │   │   ├── 1927/
│   │   │   │   ├── AAPL.json
│   │   │   │   ├── MSFT.json
│   │   │   │   └── ...
│   │   │   ├── 1928/
│   │   │   └── ...
│   │   │   └── 2026/
│   │   └── indicators/
│   │       └── standard/      # テクニカル指標
│   │           ├── 1927/
│   │           │   ├── AAPL.json
│   │           │   ├── MSFT.json
│   │           │   └── ...
│   │           └── ...
│   └── fundamentals/          # 四半期財務データ
│       ├── AAPL.json
│       ├── MSFT.json
│       └── ...
├── scores/
│   ├── RS_scores/            # Relative Strength スコア
│   │   ├── individual/
│   │   │   ├── 1927.json
│   │   │   ├── 1928.json
│   │   │   └── ...
│   │   ├── sector/
│   │   │   ├── 1927.json
│   │   │   └── ...
│   │   └── industry/
│   │       ├── 1927.json
│   │       └── ...
│   └── RRS_scores/           # Risk-adjusted Relative Strength スコア
│       ├── individual/
│       ├── sector/
│       └── industry/
└── metadata/
    └── last-updated.json     # 最終更新情報
```

---

## 📊 データ形式

### 1. Core Data (`stocks/daily/core/{year}/{symbol}.json`)

**説明**: 日次の価格データ（OHLCV）と RS/RRS スコア

**ファイルパス例**: `stocks/daily/core/2024/AAPL.json`

**データ構造**:
```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "data": [
    {
      "date": "2024-01-02",
      "open": 185.64,
      "high": 186.95,
      "low": 184.35,
      "close": 185.92,
      "volume": 54382900,
      "rs_raw": 0.0234,
      "rs_percentile": 78.5,
      "rrs_raw": 0.0189,
      "rrs_percentile": 82.3
    },
    ...
  ]
}
```

**フィールド説明**:
- `date`: 日付 (YYYY-MM-DD)
- `open/high/low/close`: 始値/高値/安値/終値 (USD)
- `volume`: 出来高
- `rs_raw`: RS 生値（S&P500 比の相対強度）
- `rs_percentile`: RS パーセンタイル（1-99、数値が大きいほど強い）
- `rrs_raw`: RRS 生値（リスク調整後の相対強度）
- `rrs_percentile`: RRS パーセンタイル（1-99）

**データ期間**: 1927年～現在（銘柄により異なる）

**更新頻度**: 毎営業日（米国市場終了後）

---

### 2. Indicators Data (`stocks/daily/indicators/standard/{year}/{symbol}.json`)

**説明**: テクニカル指標（移動平均線、RSI、ATR など）

**ファイルパス例**: `stocks/daily/indicators/standard/2024/AAPL.json`

**データ構造**:
```json
{
  "ticker": "AAPL",
  "indicators": ["sma20", "sma50", "sma200", "ema21", "rsi14", "atr14", "vwap"],
  "data": [
    {
      "date": "2024-01-02",
      "sma20": 182.45,
      "sma50": 178.92,
      "sma200": 165.34,
      "ema21": 183.12,
      "rsi14": 65.4,
      "atr14": 3.45,
      "vwap": 185.67
    },
    ...
  ]
}
```

**指標説明**:
- `sma20/50/200`: 単純移動平均（20/50/200日）
- `ema21`: 指数移動平均（21日）
- `rsi14`: Relative Strength Index（14日）
- `atr14`: Average True Range（14日）
- `vwap`: Volume Weighted Average Price


### 3. Fundamental Data (`stocks/fundamentals/quarterly/{year}/{symbol}.json`)

**説明**: 四半期ごとの財務データ（2000年〜現在、最大120四半期）

**ファイルパス例**: `stocks/fundamentals/AAPL.json`

**データソース**: Financial Modeling Prep API から以下の4つのステートメントを取得・統合
- Income Statement（損益計算書）
- Cash Flow Statement（キャッシュフロー計算書）
- Balance Sheet（貸借対照表）
- Key Metrics（主要指標）

**データ構造**:
```json
{
  "ticker": "AAPL",
  "data": [
    {
      "date": "2024-09-30",
      "eps": 1.64,
      "epsDiluted": 1.64,
      "revenue": 94930000000,
      "netIncome": 25000000000,
      "freeCashFlow": 23000000000,
      "operatingCashFlow": 26000000000,
      "stockholdersEquity": 65000000000,
      "bookValuePerShare": 4.25,
      "priceToSalesRatio": 8.5,
      "roe": 153.85
    },
    ...
  ],
  "lastUpdated": "2024-12-01T10:30:00"
}
```

**フィールド説明**:

| フィールド | 説明 | 出典 | 単位 |
|-----------|------|------|------|
| `date` | 四半期終了日 | - | YYYY-MM-DD |
| `eps` | 1株当たり利益（基本） | Income Statement | USD |
| `epsDiluted` | 1株当たり利益（希薄化後） | Income Statement | USD |
| `revenue` | 売上高 | Income Statement | USD |
| `netIncome` | 純利益 | Income Statement | USD |
| `freeCashFlow` | フリーキャッシュフロー | Cash Flow Statement | USD |
| `operatingCashFlow` | 営業キャッシュフロー | Cash Flow Statement | USD |
| `stockholdersEquity` | 株主資本 | Balance Sheet | USD |
| `bookValuePerShare` | 1株当たり純資産 (BPS) | Key Metrics | USD |
| `priceToSalesRatio` | 株価売上高倍率 (PSR) | Key Metrics | 倍 |
| `roe` | 自己資本利益率（年率換算） | 計算値 | % |

**計算ロジック**:
```python
# ROE（年率換算）
ROE = (netIncome / stockholdersEquity) × 4 × 100
```
四半期の純利益を年率換算（×4）し、株主資本で割って算出。

**データ期間**: 
- 開始: 2000年1月以降
- 最大: 120四半期（約30年分）
- 4つのステートメント全てに存在する四半期のみ含む

**更新頻度**: 月次（毎月1日）

**注意事項**:
- 全ての財務データが揃っている四半期のみ含まれる
- 企業の上場時期により利用可能なデータ期間は異なる
- `null` 値は元データに存在しない場合に発生

---

### ４. RS Scores (`scores/RS_scores/{category}/{year}.json`)

**説明**: 個別銘柄・セクター・業種ごとの Relative Strength スコア

**カテゴリ**:
- `individual`: 個別銘柄
- `sector`: セクター別
- `industry`: 業種別

**ファイルパス例**: `scores/RS_scores/individual/2024.json`

**データ構造（Individual）**:
```json
[
  {
    "date": "2024-01-02",
    "ticker": "AAPL",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "rs_raw": 0.0234,
    "rs_percentile": 78.5
  },
  ...
]
```

**データ構造（Sector）**:
```json
[
  {
    "date": "2024-01-02",
    "sector": "Technology",
    "rs_raw": 0.0198,
    "rs_percentile": 85.2
  },
  ...
]
```

**データ構造（Industry）**:
```json
[
  {
    "date": "2024-01-02",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "rs_raw": 0.0234,
    "rs_percentile": 78.5
  },
  ...
]
```

---

### 5. RRS Scores (`scores/RRS_scores/{category}/{year}.json`)

**説明**: Risk-adjusted Relative Strength スコア（ATR でリスク調整した RS）

**構造**: RS Scores と同じ（`rs_raw`/`rs_percentile` が `rrs_raw`/`rrs_percentile` に置き換わる）

**RRS の計算式**:
```
RRS = (Close - SMA200) / ATR14
```

ATR（Average True Range）でボラティリティを考慮することで、リスク調整された相対強度を測定します。

---

### 5. Metadata (`metadata/last-updated.json`)

**説明**: データの最終更新情報

**データ構造**:
```json
{
  "lastUpdated": "2026-02-02T15:30:00",
  "priceDataStartDate": "2023-02-02",
  "priceDataEndDate": "2026-02-02",
  "totalSymbols": 4656,
  "dataRetentionDays": 1000,
  "pipeline": {
    "version": "3.0.0",
    "status": "success",
    "structure": "year-based-archive-with-rrs"
  }
}
```

---

## 🔑 R2 アクセス設定

### 必要な認証情報

R2 にアクセスするには、以下の情報が必要です：
```bash
R2_ENDPOINT=https://[account-id].r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=[your-access-key-id]
R2_SECRET_ACCESS_KEY=[your-secret-access-key]
R2_BUCKET_NAME=[your-bucket-name]
```

**注意**: 上記の認証情報は別途生成・配布されます。

---

## 📥 データの取得方法

### Python (boto3)
```python
import boto3
import json

# S3互換クライアント作成
s3 = boto3.client(
    's3',
    endpoint_url='https://[account-id].r2.cloudflarestorage.com',
    aws_access_key_id='[your-access-key-id]',
    aws_secret_access_key='[your-secret-access-key]',
    region_name='auto'
)

bucket_name = '[your-bucket-name]'

# ファイル取得例: AAPL の 2024年 core data
response = s3.get_object(
    Bucket=bucket_name,
    Key='stocks/daily/core/2024/AAPL.json'
)

data = json.loads(response['Body'].read())
print(data)
```

### JavaScript (AWS SDK)
```javascript
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";

const s3Client = new S3Client({
  region: "auto",
  endpoint: "https://[account-id].r2.cloudflarestorage.com",
  credentials: {
    accessKeyId: "[your-access-key-id]",
    secretAccessKey: "[your-secret-access-key]",
  },
});

// ファイル取得
const command = new GetObjectCommand({
  Bucket: "[your-bucket-name]",
  Key: "stocks/daily/core/2024/AAPL.json",
});

const response = await s3Client.send(command);
const data = await response.Body.transformToString();
console.log(JSON.parse(data));
```

### cURL
```bash
# AWS CLI の認証情報を使用
aws s3 cp \
  s3://[bucket-name]/stocks/daily/core/2024/AAPL.json \
  ./AAPL.json \
  --endpoint-url https://[account-id].r2.cloudflarestorage.com
```

---

## 📈 データの活用例

### 1. 特定銘柄の価格データと RS スコアを取得
```python
# AAPL の 2024年データを取得
response = s3.get_object(
    Bucket=bucket_name,
    Key='stocks/daily/core/2024/AAPL.json'
)
aapl_data = json.loads(response['Body'].read())

# 最新の RS スコアを確認
latest = aapl_data['data'][-1]
print(f"Date: {latest['date']}")
print(f"Close: ${latest['close']}")
print(f"RS Percentile: {latest['rs_percentile']}")
```

### 2. セクター別の強度ランキング
```python
# 2024年のセクター RS スコアを取得
response = s3.get_object(
    Bucket=bucket_name,
    Key='scores/RS_scores/sector/2024.json'
)
sector_scores = json.loads(response['Body'].read())

# 最新日付のデータを抽出
latest_date = sector_scores[-1]['date']
latest_scores = [s for s in sector_scores if s['date'] == latest_date]

# RS パーセンタイルでソート
ranked = sorted(latest_scores, key=lambda x: x['rs_percentile'], reverse=True)

print("Sector Strength Ranking:")
for i, sector in enumerate(ranked, 1):
    print(f"{i}. {sector['sector']}: {sector['rs_percentile']:.1f}")
```

### 3. 複数年データの結合
```python
import pandas as pd

# 2023年と2024年のデータを結合
years = [2023, 2024]
all_data = []

for year in years:
    response = s3.get_object(
        Bucket=bucket_name,
        Key=f'stocks/daily/core/{year}/AAPL.json'
    )
    year_data = json.loads(response['Body'].read())
    all_data.extend(year_data['data'])

# DataFrameに変換
df = pd.DataFrame(all_data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date')

print(df.head())
```

---

## ⚠️ 注意事項

### データの品質

1. **欠損値**: 一部の銘柄で古い年のデータが存在しない場合があります
2. **上場前データ**: 銘柄の上場日以前のデータは存在しません
3. **指標の計算期間**: SMA200 などは計算に必要な期間（200日）のデータが揃うまで `null` になります

### 利用上の制限

1. **レート制限**: R2 には API リクエストの制限があります（通常使用では問題ありません）
2. **データ更新**: 毎営業日の米国市場終了後（日本時間 翌朝6:00頃）に更新されます
3. **データ保持期間**: 直近1000日分（約4年分）の daily データを保持します

### ベストプラクティス

1. **キャッシュの活用**: 同じファイルを繰り返し取得する場合はローカルにキャッシュしてください
2. **バッチ処理**: 大量のファイルを取得する場合は並列処理を検討してください
3. **エラーハンドリング**: ネットワークエラーや存在しないファイルへのアクセスに対応してください

---

## 🆘 サポート

データに関する質問や問題がある場合は、以下の情報を含めてお問い合わせください：

- アクセスしようとしたファイルパス
- エラーメッセージ（該当する場合）
- 使用しているプログラミング言語・ライブラリ

---

**Last Updated**: 2026-02-02  
**Pipeline Version**: 3.0.0  
**Data Structure**: Year-based archive with RRS support