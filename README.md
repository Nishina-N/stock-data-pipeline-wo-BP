# Stock Data Pipeline

米国株・日本株の価格/RS/ファンダメンタルズ/マクロ系列を取得し、Cloudflare R2 に年別 JSON で格納するパイプライン。

役割は **R2 への生データ取得のみ**。合成指数や派生指標（テクニカル指標等）はパイプライン側では作らない（利用側で OHLCV から再計算する方針）。

---

## 📋 パイプライン一覧

| パイプライン | ワークフロー | スケジュール | 内容 |
|---|---|---|---|
| US Daily | `daily-update.yml` | 月〜金 22:00 UTC | 価格(1000日窓) → RS計算 → core/scores 更新 + market系列(YTD) |
| JP Daily | `jp-daily-update.yml` | 月〜金 09:00 UTC (JST 18:00) | JP版の同処理（`jp/` 名前空間） |
| Intraday | `intraday-update.yml` | 取引時間中 | 当日の日中データ |
| Monthly | `monthly-fetch-stocks.yml` | 毎月 | ユニバース更新 |
| Monthly (手動) | - | 手動 | ファンダ/アナリスト予想/浮動株（`scripts/monthly/`） |

### US Daily の流れ

1. `0_download_target_stocks.py` — R2 からユニバース CSV 取得（無ければ FMP から再構築）
2. `2_fetch_price_data.py` — Yahoo Finance から直近1000日の OHLCV（失敗率2%超で中断）
3. `2.5_add_indicators.py` — pkl → JSON 変換（OHLCV のみ。指標計算は廃止済み・名前は歴史的経緯）
4. `3_calculate_rs.py` — Individual/Sector/Industry RS（percentile のみ。RRS は廃止済み）
5. `4_export_to_json.py` — 年別 JSON 生成（core + scores + metadata）
6. `5_upload_to_r2.py` — R2 アップロード（過去年は凍結、当年のみ上書き）
7. `fetch_market_series.py --strict` → `build_market_by_year.py --merge` → `upload_market_to_r2.py` — マクロ系列

---

## 🗂️ ディレクトリ構造

```
stock-data-pipeline/
├── .github/workflows/         # 上表の4ワークフロー
├── common/
│   ├── r2.py                  # R2 クライアント生成
│   ├── symbols.py             # ユニバースCSVローダー（"N/A"のNaN化対策込み）
│   ├── market_symbols.py      # US 保証銘柄（指数/ETF、単一の真実の情報源）
│   └── jp_market_symbols.py   # JP 保証銘柄（1306/^N225）
├── scripts/
│   ├── daily/                 # US 日次（0,1,2,2.5,3,4,5 + add_market_symbols_backfill）
│   ├── jp/                    # JP 日次（0〜4 + ユニバース構築/ファンダ）→ scripts/jp/README.md
│   ├── monthly/               # ファンダ/アナリスト予想/浮動株 → scripts/monthly/README.md
│   ├── market/                # マクロ系列（VIX/信用/金利/為替）→ scripts/market/README.md
│   ├── intraday/              # 日中データ
│   └── maintenance/           # 棚卸し/欠損補充/復旧ツール → scripts/maintenance/README.md
├── docs/
│   ├── R2_DATA_STRUCTURE.md   # R2 データ構造（利用者向け）
│   └── API_ACCESS.md          # 外部アクセス方法
├── data/                      # 一時ファイル（gitignore）
└── requirements.txt
```

---

## 🚀 セットアップ

### 環境変数

GitHub Actions は Settings → Secrets、ローカルは `.env`（`.env.example` 参照）:

- `FMP_API_KEY` — Financial Modeling Prep（stable API のみ。legacy /api/v3 は 403）
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT` / `R2_BUCKET_NAME`

### 依存関係

```bash
pip install -r requirements.txt
```

---

## 💻 ローカル実行

```bash
# US Daily（順次実行）
python scripts/daily/0_download_target_stocks.py
python scripts/daily/2_fetch_price_data.py
python scripts/daily/2.5_add_indicators.py
python scripts/daily/3_calculate_rs.py
python scripts/daily/4_export_to_json.py
python scripts/daily/5_upload_to_r2.py            # 過去年は凍結。--force-past で件数チェック付き上書き

# JP Daily は scripts/jp/README.md を参照
# メンテナンス（棚卸し・欠損補充・復旧）は scripts/maintenance/README.md を参照
python scripts/maintenance/check_r2_files.py       # R2 全体の棚卸し
```

Windows でのローカル実行は `PYTHONUTF8=1` を付けると cp932 起因のエンコーディングエラーを避けられる。

---

## 📊 R2 データ構造（概要）

詳細は [`docs/R2_DATA_STRUCTURE.md`](docs/R2_DATA_STRUCTURE.md) を参照。

```
r2://bucket/
├── stocks/
│   ├── daily/core/{year}/{symbol}.json     # OHLCV + rs_percentile（1927〜）
│   ├── fundamentals/quarterly/{year}/{symbol}.json
│   ├── analyst_estimates/{symbol}.json
│   └── shares_float/{symbol}.json
├── scores/RS_scores/{sector,industry}/{year}.json
├── market/daily/{year}.json                # VIX/信用/コモディティ/金利/為替の統合ファイル
├── market/metadata.json
├── metadata/                               # ユニバースCSV・last-updated
└── jp/                                     # 日本株（同構造のミラー、純コードキー）
    ├── stocks/daily/core/{year}/{code}.json
    ├── stocks/fundamentals/quarterly/{year}/{code}.json
    ├── stocks/analyst_estimates/{code}.json
    ├── stocks/shares_float/{code}.json
    ├── scores/RS_scores/{sector,industry}/{year}.json
    └── metadata/
```

- individual RS は core の `rs_percentile` に埋め込み（`scores/RS_scores/individual/` は廃止）
- indicators / RRS / summary / BuyPressure 系統は **廃止済み**（R2 からも削除済み）

---

## 📈 RS の定義（US/JP 共通）

```
rs_raw = ret_3m×0.4 + ret_6m×0.2 + ret_9m×0.2 + ret_12m×0.2   （63/126/189/252営業日リターン%）
rs_percentile = クロスセクション percentile（1〜99）、min_days=252
```

- **Sector / Industry RS**: 個別 percentile を Close×Volume（最新日）で加重平均 → グループ間で再 percentile 化
- 保証銘柄（指数/ETF、`sector='N/A'`）はグループ集計から除外（個別 RS と core には含む）
- JP の RS はベンチマーク相対ではなく US と同じクロスセクション percentile

---

## 🛡️ 安全設計（運用ルール）

1. **year-freeze**: 過去年ファイルは R2 に存在すれば上書きしない。強制上書きは `--force-past`（既存よりレコード件数が減る場合はブロック）
2. **ドライラン既定**: R2 に書くスクリプトは原則 `--execute` を付けて初めて実書込
3. **取得失敗ゲート**: yfinance の失敗率 2% 超で中断（縮んだ母集団で RS を計算しない）。market 系列は `--strict`
4. **listing 失敗時は中断**: R2 一覧取得に失敗したらアップロード全体を中止（凍結判定の前提が崩れるため）
5. **部分アップロードは失敗扱い**: 1件でもアップロード失敗があれば exit 1
6. **concurrency ガード**: schedule と手動実行の同時走行を防止

---

## 🔧 トラブルシューティング

- **GitHub Actions "Runner not acquired"**: GitHub 側の問題。Re-run で再実行
- **yfinance の空応答が続く**: レート制限の典型。時間を置いて再実行（失敗率ゲートで自動中断される）
- **アップロードが遅い**: `MAX_WORKERS`（既定10）を調整。boto3 クライアントは安定性優先で都度生成（過去に再利用で不具合実績あり）

---

## 📡 外部アクセス

[`docs/API_ACCESS.md`](docs/API_ACCESS.md) を参照（読み取り専用、Cloudflare Workers API 経由推奨）。

---

## 📄 ライセンス

Private repository - All rights reserved.
