# Stock Data Pipeline - R2 Storage Documentation

本ドキュメントは、Stock Data Pipeline が生成する R2 ストレージのデータ構造と利用方法を説明します。

> 旧版に記載されていた `indicators/`・`RRS_scores/`・`scores/RS_scores/individual/`・
> `rs_raw`/`rrs_*` フィールドは **廃止済み** です（R2 からも削除済み）。
> individual RS は core の `rs_percentile` に統合されています。

---

## 📁 フォルダ構造

```
r2://your-bucket/
├── stocks/
│   ├── daily/core/{year}/{symbol}.json        # OHLCV + rs_percentile（1927〜現在）
│   ├── fundamentals/quarterly/{year}/{symbol}.json  # 四半期財務（2000〜）
│   ├── analyst_estimates/{symbol}.json        # アナリスト予想（年別なし・常に最新）
│   └── shares_float/{symbol}.json             # 浮動株（現在値スナップショット）
├── scores/
│   └── RS_scores/
│       ├── sector/{year}.json                 # セクター RS（11グループ）
│       └── industry/{year}.json               # 業種 RS（約150グループ）
├── market/
│   ├── daily/{year}.json                      # マクロ系列の統合ファイル（下記）
│   └── metadata.json                          # 系列一覧・カバレッジ実測
├── metadata/
│   ├── target_stocks_latest.csv               # ユニバース（保証銘柄含む）
│   └── last-updated.json                      # 最終更新情報
└── jp/                                        # 日本株（純コードキー。例 7203, 130A）
    ├── stocks/daily/core/{year}/{code}.json
    ├── stocks/fundamentals/quarterly/{year}/{code}.json
    ├── stocks/analyst_estimates/{code}.json
    ├── stocks/shares_float/{code}.json
    ├── scores/RS_scores/{sector,industry}/{year}.json   # 17業種 / 33業種（東証区分）
    └── metadata/
        ├── target_stocks_jp_latest.csv
        └── last-updated.json
```

---

## 📊 データ形式

### 1. Core Data (`stocks/daily/core/{year}/{symbol}.json`)

日次 OHLCV + 個別 RS percentile。

```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "data": [
    {
      "date": "2024-01-02",
      "open": 185.64, "high": 186.95, "low": 184.35, "close": 185.92,
      "volume": 54382900,
      "rs_percentile": 78.5
    }
  ]
}
```

- `rs_percentile`: 1〜99 のクロスセクション percentile（大きいほど強い）。
  計算に 252 営業日必要なため、上場直後や履歴不足期間は `null`
- 指数/ETF の保証銘柄（`^GSPC`, `SPY`, `TQQQ` 等）は `sector`/`industry` が `"N/A"`
- 過去年ファイルは凍結（変更されない）。当年ファイルのみ毎営業日更新

**RS の定義**: `ret_3m×0.4 + ret_6m×0.2 + ret_9m×0.2 + ret_12m×0.2`（63/126/189/252営業日リターン%）を全銘柄間で percentile 化。

### 2. RS Scores (`scores/RS_scores/{sector,industry}/{year}.json`)

個別 RS percentile を Close×Volume（最新日）で加重平均し、グループ間で再 percentile 化した値。

```json
[
  {
    "date": "2024-01-02",
    "sector": "Technology",
    "rs_percentile": 85.2,
    "rank": 2,
    "stock_count": 612
  }
]
```

- `rank`: その日のグループ内順位（1 = 最強）
- `industry` ファイルには所属 `sector` フィールドが追加で付く
- `sector`/`industry` が `"N/A"` の銘柄（指数/ETF）はランキング母数に含まれない

### 3. Fundamentals (`stocks/fundamentals/quarterly/{year}/{symbol}.json`)

FMP stable API 由来の四半期財務（`period=quarter` のみ。TTM/annual は不使用）。

フィールド（19項目）:

```
date, eps, epsDiluted, revenue, netIncome, freeCashFlow, operatingCashFlow,
stockholdersEquity, bookValuePerShare,
roeQuarterly, roe, roicQuarterly, roic,
earningsDate, epsActual, epsEstimated, epsSurprisePct,
revenueEstimated, revenueSurprisePct
```

- `roe`/`roic` は単一四半期値の×4 年率化（TTM 合算ではない＝リーク無し）
- `earningsDate` は**決算発表日**（point-in-time 用）。`date`（会計期末）とは別軸。
  リーク防止には必ず `earningsDate` を使うこと
- `priceToSalesRatio` は廃止（2026-07-08。分母が単一四半期売上で歪むため）

### 4. Analyst Estimates (`stocks/analyst_estimates/{symbol}.json`)

`analyst-estimates?period=annual` 由来。年別パーティション無し、常に最新で上書き。

```
date, revenueLow/High/Avg, ebitdaLow/High/Avg, netIncomeLow/High/Avg,
epsLow/High/Avg, numAnalystsRevenue, numAnalystsEps
```

### 5. Shares Float (`stocks/shares_float/{symbol}.json`)

現在値スナップショット（過去時系列は無い）: `freeFloat`, `floatShares`, `outstandingShares`

### 6. Market Series (`market/daily/{year}.json`)

リスク制御用マクロ系列の統合ファイル。`{"year", "tickers", "data": {date: {ticker: ohlcv}}}` 形式。

| 分類 | ティッカー |
|---|---|
| ボラティリティ | `^VIX`, `^VIX3M` |
| 信用 | `HYG`, `JNK`, `LQD`, `IEI` |
| リスク選好/ベンチマーク | `IWM`, `SPY` |
| コモディティ/ドル | `HG=F`, `GC=F`, `CL=F`, `DX-Y.NYB`, `TIP`, `IEF`, `DBC`, `DBB` |
| 米金利（FMP treasury-rates） | `UST2Y`, `UST10Y`, `UST30Y`（1990〜） |
| JP マクロ | `USDJPY=X`（1996〜）, `JGB2Y`（1974〜）, `JGB10Y`（1986〜、財務省CSV） |

金利系は擬似 OHLCV（open=high=low=close=利回り%、volume=null）。
系列一覧と実測カバレッジは `market/metadata.json` を参照。

### 7. JP データ (`jp/` プレフィックス)

US と同構造のミラー。相違点:

- キーは純コード（`.T` なし。例 `7203`）。英数字コードあり（`130A` 等）
- sector=17業種 / industry=33業種（東証区分）
- ベンチマーク疑似ティッカー: `1306`（TOPIX ETF）, `^N225`（日経225）。
  sector/industry は `"N/A"` でグループ集計から除外
- 通貨 JPY

### 8. Metadata (`metadata/last-updated.json`)

```json
{
  "lastUpdated": "2026-08-12T22:58:01",
  "priceDataStartDate": "2024-11-18",
  "priceDataEndDate": "2026-08-12",
  "totalSymbols": 4500,
  "dataRetentionDays": 500,
  "pipeline": {
    "version": "4.0.0",
    "status": "success",
    "structure": "year-based-archive-rs-only"
  }
}
```

`priceDataStartDate`/`EndDate` は**当日の RS 出力窓（直近500営業日）**を示す。
core の実データはこれより長く 1927 年〜（過去年ファイルとして凍結保存）。

---

## 🔑 R2 アクセス設定

```bash
R2_ENDPOINT=https://[account-id].r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=[your-access-key-id]
R2_SECRET_ACCESS_KEY=[your-secret-access-key]
R2_BUCKET_NAME=[your-bucket-name]
```

認証情報は別途生成・配布されます。

---

## 📥 データの取得方法

### Python (boto3)

```python
import boto3
import json

s3 = boto3.client(
    's3',
    endpoint_url='https://[account-id].r2.cloudflarestorage.com',
    aws_access_key_id='[your-access-key-id]',
    aws_secret_access_key='[your-secret-access-key]',
    region_name='auto'
)

response = s3.get_object(
    Bucket='[your-bucket-name]',
    Key='stocks/daily/core/2024/AAPL.json'
)
data = json.loads(response['Body'].read())
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

const response = await s3Client.send(new GetObjectCommand({
  Bucket: "[your-bucket-name]",
  Key: "stocks/daily/core/2024/AAPL.json",
}));
const data = JSON.parse(await response.Body.transformToString());
```

---

## 📈 活用例

### セクター別の強度ランキング

```python
response = s3.get_object(Bucket=bucket, Key='scores/RS_scores/sector/2024.json')
sector_scores = json.loads(response['Body'].read())

latest_date = max(s['date'] for s in sector_scores)
latest = [s for s in sector_scores if s['date'] == latest_date]
for s in sorted(latest, key=lambda x: x['rank']):
    print(f"{s['rank']:2}. {s['sector']}: {s['rs_percentile']:.1f}")
```

### 複数年データの結合

```python
import pandas as pd

all_data = []
for year in [2023, 2024]:
    response = s3.get_object(Bucket=bucket, Key=f'stocks/daily/core/{year}/AAPL.json')
    all_data.extend(json.loads(response['Body'].read())['data'])

df = pd.DataFrame(all_data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date')
```

---

## ⚠️ 注意事項

1. **欠損値**: 上場前・履歴不足期間のデータは存在しない。`rs_percentile` は 252 営業日の履歴が揃うまで `null`
2. **更新タイミング**: US は毎営業日 22:00 UTC 以降、JP は毎営業日 09:00 UTC (JST 18:00) 以降
3. **過去年は不変**: 過去年ファイルは凍結されており CDN キャッシュ可能。当年ファイルのみ毎日変わる
4. **キャッシュ/並列/エラーハンドリング**: 繰り返し取得はローカルキャッシュ、大量取得は並列化、存在しないキーへの対応を推奨

---

**Last Updated**: 2026-08-13
**Pipeline Version**: 4.0.0
**Data Structure**: year-based-archive-rs-only
