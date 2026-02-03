# Stock Data API Access Guide

R2 ストレージに保存された株式データへのアクセス方法。

---

## 🔑 認証情報

以下の認証情報を使用してデータにアクセスできます（**読み取り専用**）：
```bash
R2_ENDPOINT=https://90c99ec69c4bade0361ceab347ebdb1d.r2.cloudflarestorage.com
R2_BUCKET_NAME=stock-data

R2_ACCESS_KEY_ID=[別途共有]
R2_SECRET_ACCESS_KEY=[別途共有]

```

⚠️ **注意**: この認証情報は読み取り専用です。データの変更・削除はできません。

---

## 🌐 アクセス方法

### Option 1: Cloudflare Workers API（推奨）

公開 API エンドポイント：
```
https://trading-dashboard-api.your-subdomain.workers.dev
```

**利用可能なエンドポイント**:
```
GET /api/stocks/core/{year}/{symbol}
GET /api/stocks/indicators/{year}/{symbol}
GET /api/scores/RS_scores/{category}/{year}
GET /api/scores/RRS_scores/{category}/{year}
GET /api/metadata
```

**使用例**:
```bash
# AAPL の 2024年 core data
curl https://trading-dashboard-api.your-subdomain.workers.dev/api/stocks/core/2024/AAPL

# Individual RS scores for 2024
curl https://trading-dashboard-api.your-subdomain.workers.dev/api/scores/RS_scores/individual/2024
```

---

### Option 2: 直接 R2 アクセス（AWS SDK）

認証情報を使って直接 R2 からデータを取得できます。

#### JavaScript/TypeScript
```typescript
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";

const s3Client = new S3Client({
  region: "auto",
  endpoint: "https://[account-id].r2.cloudflarestorage.com",
  credentials: {
    accessKeyId: "[public-readonly-key-id]",
    secretAccessKey: "[public-readonly-secret-key]",
  },
});

// ファイル取得
const command = new GetObjectCommand({
  Bucket: "[bucket-name]",
  Key: "stocks/daily/core/2024/AAPL.json",
});

const response = await s3Client.send(command);
const data = await response.Body?.transformToString();
console.log(JSON.parse(data));
```

#### Python
```python
import boto3
import json

s3 = boto3.client(
    's3',
    endpoint_url='https://[account-id].r2.cloudflarestorage.com',
    aws_access_key_id='[public-readonly-key-id]',
    aws_secret_access_key='[public-readonly-secret-key]',
    region_name='auto'
)

# ファイル取得
response = s3.get_object(
    Bucket='[bucket-name]',
    Key='stocks/daily/core/2024/AAPL.json'
)

data = json.loads(response['Body'].read())
print(data)
```

#### cURL
```bash
# AWS CLI を使用
aws s3 cp \
  s3://[bucket-name]/stocks/daily/core/2024/AAPL.json \
  - \
  --endpoint-url https://[account-id].r2.cloudflarestorage.com \
  --profile r2-readonly
```

---

## 📊 データ構造

詳細は [`R2_DATA_STRUCTURE.md`](R2_DATA_STRUCTURE.md) を参照。

### 主要なデータパス
```
stocks/daily/core/{year}/{symbol}.json          # 価格 + RS/RRS
stocks/daily/indicators/standard/{year}/{symbol}.json  # テクニカル指標
scores/RS_scores/individual/{year}.json         # Individual RS
scores/RS_scores/sector/{year}.json             # Sector RS
scores/RS_scores/industry/{year}.json           # Industry RS
scores/RRS_scores/individual/{year}.json        # Individual RRS
scores/RRS_scores/sector/{year}.json            # Sector RRS
scores/RRS_scores/industry/{year}.json          # Industry RRS
metadata/last-updated.json                      # 最終更新情報
```

---

## 💡 使用例

### 例1: 特定銘柄の価格データ取得
```typescript
// Workers API 経由（推奨）
const response = await fetch(
  'https://trading-dashboard-api.your-subdomain.workers.dev/api/stocks/core/2024/AAPL'
);
const data = await response.json();

console.log(data.ticker);  // "AAPL"
console.log(data.data);    // 価格データ配列
```

### 例2: RS スコアランキング取得
```typescript
const response = await fetch(
  'https://trading-dashboard-api.your-subdomain.workers.dev/api/scores/RS_scores/individual/2024'
);
const scores = await response.json();

// RS パーセンタイルでソート
const ranked = scores
  .filter(s => s.date === '2024-12-31')
  .sort((a, b) => b.rs_percentile - a.rs_percentile);

console.log('Top 10 by RS:');
ranked.slice(0, 10).forEach((s, i) => {
  console.log(`${i+1}. ${s.ticker}: ${s.rs_percentile}`);
});
```

### 例3: セクター強度比較
```typescript
const response = await fetch(
  'https://trading-dashboard-api.your-subdomain.workers.dev/api/scores/RS_scores/sector/2024'
);
const sectors = await response.json();

// 最新日のデータ
const latest = sectors.filter(s => s.date === '2024-12-31');
const sorted = latest.sort((a, b) => b.rs_percentile - a.rs_percentile);

console.log('Sector Rankings:');
sorted.forEach((s, i) => {
  console.log(`${i+1}. ${s.sector}: ${s.rs_percentile}`);
});
```

---

## 🚨 制限事項

### レート制限

- R2 への直接アクセス: 制限なし（通常使用では問題なし）
- Workers API: Cloudflare Free プランの制限に準拠

### データ更新頻度

- 毎営業日（月〜金）の米国市場終了後に更新
- 日本時間で翌朝 6:00 頃

### キャッシュ

- Workers API はデフォルトで 1 時間キャッシュ
- 最新データが必要な場合は更新後 1 時間待つか、直接 R2 にアクセス

---

## 📞 サポート

データ構造や API に関する質問は、GitHub Issues または担当者に連絡してください。
```

---

## セキュリティ設定の確認

### 読み取り専用キーの権限

作成した API キーが以下のみ許可されていることを確認：
```
✅ Object Read (GetObject, ListBucket)
❌ Object Write (PutObject, DeleteObject)
❌ Bucket Management