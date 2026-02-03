# Stock Data Pipeline

株式データの収集、テクニカル指標計算、RS/RRS スコア算出、Cloudflare R2 へのアップロードを自動化するパイプライン。

---

## 📋 概要

このパイプラインは以下の処理を実行します：

### Daily Pipeline（毎営業日実行）
1. **銘柄リスト取得**: R2 から最新の銘柄リストをダウンロード（存在しない場合は FMP API から取得）
2. **価格データ取得**: Yahoo Finance から直近 1000 日分の価格データを取得
3. **指標計算**: テクニカル指標（SMA, EMA, RSI, ATR, VWAP）を計算
4. **RS/RRS 計算**: Individual/Sector/Industry の Relative Strength と Risk-adjusted Relative Strength を計算
5. **JSON エクスポート**: 年別に分割した JSON ファイルを生成
6. **R2 アップロード**: Cloudflare R2 に並列アップロード（過去年度はスマートスキップ）

### Maintenance Pipeline（履歴データ処理）
- 1927年〜現在までの全履歴データを年別に処理
- メモリリーク対策済みの並列アップロード
- null データの自動スキップ

---

## 🗂️ ディレクトリ構造
```
stock-data-pipeline/
├── .github/
│   └── workflows/
│       ├── daily-update.yml          # Daily 自動実行（月〜金 21:00 UTC）
│       └── monthly-fetch-stocks.yml  # Monthly 銘柄リスト更新
├── scripts/
│   ├── daily/                        # Daily パイプライン
│   │   ├── 0_download_target_stocks.py  # R2 から銘柄リスト取得
│   │   ├── 1_fetch_target_stocks.py     # FMP API から銘柄取得（0 から呼ばれる）
│   │   ├── 2_fetch_price_data.py        # 価格データ取得（1000日分）
│   │   ├── 2.5_add_indicators.py        # テクニカル指標計算
│   │   ├── 3_calculate_rs.py            # RS/RRS 計算
│   │   ├── 4_export_to_json.py          # JSON エクスポート（年別）
│   │   └── 5_upload_to_r2.py            # R2 アップロード
│   ├── maintenance/                  # Maintenance パイプライン
│   │   ├── 1_fetch_historical_prices.py     # 履歴価格データ取得
│   │   ├── 2_add_indicators.py              # 指標計算
│   │   ├── 3_calculate_rs.py                # RS/RRS 計算
│   │   ├── 4_1_export_individual_rs.py      # Individual RS エクスポート
│   │   ├── 4_2_export_individual_rrs.py     # Individual RRS エクスポート
│   │   ├── 4_3_export_sector_industry.py    # Sector/Industry エクスポート
│   │   ├── 4_4_export_historical_by_year.py # 年別エクスポート
│   │   ├── 5_1_upload_individual_rs_to_r2.py    # Individual RS アップロード
│   │   ├── 5_2_upload_individual_rrs_to_r2.py   # Individual RRS アップロード
│   │   ├── 5_3_upload_sector_industry_to_r2.py  # Sector/Industry アップロード
│   │   ├── 5_4_upload_historical_by_year.py     # 年別アップロード
│   │   ├── check_r2_files.py                    # R2 ファイル数確認
│   │   └── process_all_historical_years.sh      # 全年一括処理
│   └── monthly/                      # Monthly パイプライン
│       └── ...
├── docs/
│   └── R2_DATA_STRUCTURE.md          # R2 データ構造ドキュメント
├── data/                             # 一時ファイル（gitignore）
│   ├── daily/
│   │   └── r2/                       # Daily の R2 アップロード用
│   └── maintenance/
│       └── r2/                       # Maintenance の R2 アップロード用
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 セットアップ

### 1. 環境変数の設定

#### GitHub Actions 用（Secrets）

リポジトリの Settings → Secrets and variables → Actions で以下を設定：

- `FMP_API_KEY`: Financial Modeling Prep API キー
- `R2_ACCESS_KEY_ID`: Cloudflare R2 アクセスキー ID
- `R2_SECRET_ACCESS_KEY`: Cloudflare R2 シークレットアクセスキー
- `R2_ENDPOINT`: R2 エンドポイント URL（例: `https://account-id.r2.cloudflarestorage.com`）
- `R2_BUCKET_NAME`: R2 バケット名

#### ローカル開発用（.env）
```bash
# .env ファイルを作成
cp .env.example .env

# .env を編集
cat > .env << EOF
FMP_API_KEY=your_fmp_api_key
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_ENDPOINT=https://your-account-id.r2.cloudflarestorage.com
R2_BUCKET_NAME=your-bucket-name
EOF
```

### 2. 依存関係のインストール
```bash
pip install -r requirements.txt
```

**主な依存パッケージ**:
- `yfinance`: Yahoo Finance からの価格データ取得
- `pandas`, `numpy`: データ処理
- `boto3`: R2 アップロード
- `python-dotenv`: 環境変数管理

---

## 💻 使用方法

### Daily Pipeline（ローカル実行）
```bash
# 全ステップを順次実行
python3 scripts/daily/0_download_target_stocks.py
python3 scripts/daily/2_fetch_price_data.py
python3 scripts/daily/2.5_add_indicators.py
python3 scripts/daily/3_calculate_rs.py
python3 scripts/daily/4_export_to_json.py
python3 scripts/daily/5_upload_to_r2.py

# クリーンアップ
rm -rf data/daily/*
```

### Maintenance Pipeline（履歴データ処理）
```bash
# 全年データの一括処理（1927-2024）
chmod +x scripts/maintenance/process_all_historical_years.sh
nohup scripts/maintenance/process_all_historical_years.sh > process_historical.log 2>&1 &

# 進捗確認
tail -f process_historical.log

# 特定の年だけ処理
python3 scripts/maintenance/4_4_export_historical_by_year.py --year 2024
python3 scripts/maintenance/5_4_upload_historical_by_year.py --year 2024 --workers 10
```

### R2 ファイル数確認
```bash
python3 scripts/maintenance/check_r2_files.py
```

---

## 🤖 GitHub Actions

### 自動実行スケジュール

- **Daily Update**: 月〜金 21:00 UTC（日本時間 翌朝 6:00）
  - 米国市場終了後に自動実行
  - タイムアウト設定: 60分
  
- **Monthly Update**: 毎月1日 00:00 UTC
  - 銘柄リストの更新

### 手動実行

GitHub リポジトリの **Actions** タブから：
1. "Daily Stock Data Update" を選択
2. "Run workflow" をクリック
3. Branch: main を選択して実行

---

## 📊 R2 データ構造

詳細は [`docs/R2_DATA_STRUCTURE.md`](docs/R2_DATA_STRUCTURE.md) を参照。

### フォルダ構成概要
```
r2://your-bucket/
├── stocks/daily/
│   ├── core/{year}/{symbol}.json           # OHLCV + RS/RRS
│   └── indicators/standard/{year}/{symbol}.json  # テクニカル指標
├── scores/
│   ├── RS_scores/
│   │   ├── individual/{year}.json          # 個別銘柄 RS
│   │   ├── sector/{year}.json              # セクター RS
│   │   └── industry/{year}.json            # 業種 RS
│   └── RRS_scores/
│       ├── individual/{year}.json          # 個別銘柄 RRS
│       ├── sector/{year}.json              # セクター RRS
│       └── industry/{year}.json            # 業種 RRS
└── metadata/
    └── last-updated.json                   # 最終更新情報
```

### データ期間

- **Daily データ**: 直近 1000 日分（約 4 年）
- **Historical データ**: 1927 年〜現在（銘柄により異なる）

---

## 📈 計算指標

### テクニカル指標

| 指標 | 説明 | パラメータ |
|------|------|-----------|
| SMA20/50/200 | 単純移動平均 | 20/50/200 日 |
| EMA21 | 指数移動平均 | 21 日 |
| RSI14 | Relative Strength Index | 14 日 |
| ATR14 | Average True Range | 14 日 |
| VWAP | Volume Weighted Average Price | 当日 |

### RS/RRS スコア

#### RS (Relative Strength)

**計算式**:
```
RS_raw = ret_3m × 0.4 + ret_6m × 0.2 + ret_9m × 0.2 + ret_12m × 0.2
```

ここで：
- `ret_3m` = 過去3ヶ月（63営業日）のリターン（%）
- `ret_6m` = 過去6ヶ月（126営業日）のリターン（%）
- `ret_9m` = 過去9ヶ月（189営業日）のリターン（%）
- `ret_12m` = 過去12ヶ月（252営業日）のリターン（%）

**説明**:
- 複数期間のリターンを加重平均し、短期（3ヶ月）に重み（40%）を置く
- 生値（`rs_raw`）を計算後、全銘柄間でパーセンタイル化（1-99）
- 値が高いほど相対的に強い銘柄

#### RRS (Risk-adjusted Relative Strength)

**計算式**:
```
RRS_daily = (ΔStock - ΔS&P500 × (ATR_stock / ATR_S&P500)) / ATR_stock
RRS = Σ(RRS_daily)  # 過去12営業日の合計
```

ここで：
- `ΔStock` = 銘柄の日次変化額
- `ΔS&P500` = S&P500 の日次変化額
- `ATR_stock` = 銘柄の ATR（14日、Average True Range）
- `ATR_S&P500` = S&P500 の ATR（14日）

**説明**:
- S&P500 との比較で期待リターンを計算
- ATR（ボラティリティ）で正規化することでリスク調整
- 過去12日間の累積値を使用
- より安定した（ボラティリティの低い）銘柄が高スコアになる傾向

#### 集計レベル

- **Individual**: 個別銘柄ごと
- **Sector**: セクターごと（時価総額 × 出来高で加重平均）
  - 重み = Close × Volume（最新日）
- **Industry**: 業種ごと（時価総額 × 出来高で加重平均）
  - 重み = Close × Volume（最新日）

**パーセンタイル化**:
- すべての生値（raw）を 1-99 のパーセンタイルに変換
- 99 に近いほど強い（上位 1%）
- 1 に近いほど弱い（下位 1%）
#### 集計レベル
- **Individual**: 個別銘柄ごと
- **Sector**: セクターごと（時価総額加重平均）
- **Industry**: 業種ごと（時価総額加重平均）

---

## ⚡ パフォーマンス最適化

### 実装済みの最適化

1. **JSON 変換の高速化** (2-3倍)
   - `.iterrows()` → `.values` でアクセス
   - リスト内包表記で一括変換

2. **Export 処理の高速化** (3-5倍)
   - NumPy 配列での事前計算
   - 日付変換の一括処理

3. **メモリリーク対策**
   - スレッドごとに新しい S3 クライアント作成
   - 明示的な `close()` 処理

4. **並列アップロード**
   - ThreadPoolExecutor (workers=10-20)
   - スマートスキップ（既存ファイルは再アップロードしない）

---

## 🔧 トラブルシューティング

### Segmentation Fault が発生する

**原因**: メモリリーク、並列度が高すぎる

**対策**:
```bash
# workers を減らす
python3 scripts/maintenance/5_4_upload_historical_by_year.py --year 2024 --workers 5
```

### GitHub Actions で "Runner not acquired" エラー

**原因**: GitHub のインフラ問題

**対策**:
1. "Re-run all jobs" で再実行
2. タイムアウト設定（既に実装済み）

### R2 アップロードが遅い

**対策**:
```bash
# workers を増やす（推奨: 10）
python3 scripts/daily/5_upload_to_r2.py
# デフォルトで workers=20 設定済み
```

---

## 📝 開発メモ

### データフロー
```
[FMP API] → target_stocks_latest.csv
    ↓
[Yahoo Finance] → temp_prices.pkl (1000日分)
    ↓
[指標計算] → temp_prices_with_indicators.pkl
    ↓
[RS/RRS 計算] → temp_rs_*.json, temp_rrs_*.json (6種類)
    ↓
[Export] → data/daily/r2/ (年別 JSON)
    ↓
[Upload] → Cloudflare R2
```

### 年別アーキテクチャの利点

1. **R2 の制約に対応**: サーバーサイドでのデータ結合不可
2. **クライアント最適化**: 必要な年だけダウンロード
3. **キャッシュ効率**: 過去年度は変更されないため CDN でキャッシュ可能

---

## 🤝 貢献

このリポジトリは private です。

---

## 📄 ライセンス

Private repository - All rights reserved.

---

## 📞 サポート

データ構造や利用方法については [`docs/R2_DATA_STRUCTURE.md`](docs/R2_DATA_STRUCTURE.md) を参照してください。