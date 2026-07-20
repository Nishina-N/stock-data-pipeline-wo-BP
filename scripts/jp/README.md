# scripts/jp — 日本株パイプライン

日本株（東証プライム/スタンダード/グロースの内国株式）を US と同じデータモデルで
整備する。名前空間は R2 上で `jp/` に完全分離（US 既存には一切触れない）。

- 業種分類: **Sector = 17業種区分 / Industry = 33業種区分**（東証区分。GICS に変換しない）
- コード表記: `.T` 抜きの純コード（例 7203、新形式 130A も文字列で対応）。yfinance 取得時のみ `.T` を付与
- 通貨: JPY・auto_adjust（調整後 OHLC）
- ベンチマーク疑似ティッカー: `1306`(TOPIX ETF, 2009〜) / `^N225`(日経225, 2004〜) を
  `common/jp_market_symbols.py`（`JP_MARKET_SYMBOLS`）で定義し、ユニバースCSVに常時注入
  （US の `common/market_symbols.py` と同じ規約。sector/industry='N/A' でグループRS集計から除外）

## スクリプト

| # | スクリプト | 役割 | 主な出力 |
|---|-----------|------|---------|
| 0 | `0_download_jp_universe.py` | R2からユニバースCSVをダウンロード（無ければ`build_jp_universe.py --execute`で再構築） | `data/target_stocks_jp_latest.csv` |
| 0 | `build_jp_universe.py` | JPX `data_j.xls` からユニバース構築 + `JP_MARKET_SYMBOLS` 注入 | `data/target_stocks_jp_latest.csv`, R2 `jp/metadata/…csv` |
| 1 | `1_fetch_jp_prices.py` | yfinance で価格取得 → OHLCV JSON（`^`始まりは`.T`を付けない） | `data/temp_prices_jp.json` / `.pkl` |
| 2 | `2_calculate_jp_rs.py` | Individual / Sector / Industry RS 計算 | `data/temp_rs_*_jp.json` |
| 3 | `3_export_jp_json.py` | 価格+RS を年別 JSON 化 | `data/jp/r2/jp/…` |
| 4 | `4_upload_jp_r2.py` | R2 へアップロード（過去年凍結・当年上書き） | R2 `jp/…` |

## RS 定義（US と同一）
- Individual: 3/6/9/12か月リターンを 0.4/0.2/0.2/0.2 で加重 → クロスセクション percentile(1–99)。`min_days=252`
- Sector/Industry: individual percentile を Close×Volume で加重平均 → グループ間で再 percentile
- core には `rs_percentile` を埋め込み。scores は sector/industry のみ（individual は core と重複のため出力しない）

## 初期シード手順（フル履歴 2004〜）
```bash
# 1. 少数ドライランで疎通確認
python scripts/jp/1_fetch_jp_prices.py --limit 30 --start 2004-01-01
python scripts/jp/2_calculate_jp_rs.py
python scripts/jp/3_export_jp_json.py
python scripts/jp/4_upload_jp_r2.py            # dry-run（既定）

# 2. 全件フル履歴
python scripts/jp/1_fetch_jp_prices.py --start 2004-01-01
python scripts/jp/2_calculate_jp_rs.py         # 全期間出力（--output-days 既定 100000）
python scripts/jp/3_export_jp_json.py
python scripts/jp/4_upload_jp_r2.py --execute  # 実投入（過去年は凍結）
```
※ `1306` / `^N225` は通常銘柄と同じ daily core パイプラインに乗るため、ユニバースCSVが
  `build_jp_universe.py` で再生成済み（`JP_MARKET_SYMBOLS` 注入込み）であることを確認してから 1 を実行する。
※ Windows では `PYTHONUTF8=1` を付けて実行（cp932 の UnicodeEncodeError 回避）。
※ 再シード前に `data/jp/r2/` を掃除してから export すると、旧サンプルの残骸が混ざらない。

## 安全弁
- `4_upload_jp_r2.py` は**既定ドライラン**。`--execute` で実投入、`--force-past` でスキーマ変更時に過去年も上書き
- 過去年ファイルは「R2 に無ければ書く」で凍結（US と同じ freeze 方針）

## 日次自動更新（`.github/workflows/jp-daily-update.yml`、2026-07-21〜）
- cron: 平日 UTC 09:00（JST 18:00、東証引け後）+ `workflow_dispatch`
- 手順: `0_download_jp_universe.py` → `1_fetch_jp_prices.py --start <直近1000日>` →
  `2_calculate_jp_rs.py` → `3_export_jp_json.py` → `4_upload_jp_r2.py --execute`
- `2_calculate_jp_rs.py`/`3_export_jp_json.py` に日数指定オプションは無く、常にpkl全体を処理する。
  直近1000日を取得すれば `min_days=252` を十分満たした状態で当年を計算できる
  （どの月に実行しても当年開始日より十分前から履歴があるため）
- 過去年ファイルは `4_upload_jp_r2.py` の年凍結ロジックで保護される。**注意**: 以前は
  `extract_year_from_path` がディレクトリ名の4桁年しか見ておらず、`RS_scores/{sector,industry}/{年}.json`
  のようにファイル名にのみ年がある形式では年を検出できず「current-year扱い」で毎回上書き対象に
  なっていた（2026-07-21修正）。日次実行時に「取得ウィンドウ開始付近で個別RSが252日未満のため
  NaN」になった過去年が誤って上書きされる事故を未然に防ぐための修正
- マクロ（日経VI）は公式ソースの制約でペンディング
