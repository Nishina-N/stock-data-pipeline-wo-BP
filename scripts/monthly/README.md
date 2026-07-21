# scripts/monthly — 米国株ファンダメンタルズ・付随データ（月次）

## スクリプト

| スクリプト | 役割 | R2出力 |
|---|---|---|
| `fetch_fundamentals.py` / `upload_fundamentals_to_r2.py` | 四半期ファンダ（財務3表/ROE/ROIC/決算サプライズ、`period=quarter`のみ） | `stocks/fundamentals/quarterly/{年}/{symbol}.json`（year-freeze） |
| `fetch_analyst_estimates.py` / `upload_analyst_estimates_to_r2.py` | アナリスト予想（`analyst-estimates?period=annual`、revenue/eps等のlow/high/avg、過去確定年〜将来数年） | `stocks/analyst_estimates/{symbol}.json`（年別パーティション無し・常に上書き） |
| `fetch_shares_float.py` / `upload_shares_float_to_r2.py` | 浮動株（`shares-float`、freeFloat/floatShares/outstandingShares） | `stocks/shares_float/{symbol}.json`（現在値スナップショット・常に上書き） |
| `upload_target_stocks_to_r2.py` | ユニバースCSVのアップロード | `metadata/target_stocks_latest.csv` |

## 設計メモ

- アナリスト予想・浮動株は**年別パーティションをしない**（fundamentalsの実績値と違い、推定値は改定される・
  浮動株は現在値スナップショットしか無いため、過去年を凍結する意味が無い）。取得のたびに全体を上書き
- 全スクリプト共通でレート制限対策の既定値 `MAX_WORKERS=3` / `REQUEST_DELAY=0.5s`（`--workers`/`--delay`で調整可）
- `upload_analyst_estimates_to_r2.py` / `upload_shares_float_to_r2.py` に**ドライランモードは無い**（実行=即書込）

## 使い方

```bash
# ファンダ（既存）
python scripts/monthly/fetch_fundamentals.py --limit 30   # ドライラン
python scripts/monthly/fetch_fundamentals.py               # 全件
python scripts/monthly/upload_fundamentals_to_r2.py         # year-freeze投入

# アナリスト予想
python scripts/monthly/fetch_analyst_estimates.py
python scripts/monthly/upload_analyst_estimates_to_r2.py

# 浮動株
python scripts/monthly/fetch_shares_float.py
python scripts/monthly/upload_shares_float_to_r2.py
```

いずれも月次実行想定（`monthly-fetch-stocks.yml`への組み込みは未着手、現状は手動運用）。
