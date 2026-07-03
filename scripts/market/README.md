# scripts/market

リスク制御用の**マクロ/マーケットシリーズ**を Yahoo Finance から取得し、
R2 の独立名前空間 `market/` に年別統合ファイルとして格納する。

株式ユニバース（`stocks/daily/core/`）とは別レイヤー。VIX 系は指数（`^`付き・売買不可・
volume なし）で、用途も「日付軸で複数シリーズを揃えて比率・微分を計算」するリスク管理。

## 格納構造（R2）

```
market/daily/{year}.json    … 全シリーズを日付キーで統合（OHLCV、無い項目は null / キー欠落）
market/metadata.json        … シリーズ定義・出典・カバレッジ・adjust方針
```

`market/daily/{year}.json` の形:

```json
{
  "year": 2024,
  "adjust": "auto_adjusted_close",
  "tickers": ["^VIX","^VIX3M","HYG","JNK","LQD","IEI","IWM","SPY"],
  "data": {
    "2024-08-05": {
      "^VIX": {"open":23.4,"high":65.7,"low":23.4,"close":38.6,"volume":null},
      "HYG":  {"open":68.6,"high":69.2,"low":68.5,"close":69.1,"volume":104456100},
      "...":  "..."
    }
  }
}
```

- **統合・年別**を採用（銘柄別ではなく）。リスク計算で全シリーズを 1 ファイルで日付整列でき、
  `^` を含むティッカーも JSON キーなので扱える。
- カバレッジが揃わない年はそのティッカーのキーが欠落（日付行自体は他シリーズで存在）。
  例: 1990=`^VIX`のみ、1993=+SPY、2000=+IWM、2007=全8。
- **auto_adjust 済み終値**。比率（HYG/IEI 等）はトータルリターン的に adjusted が適切。
- SPY/IWM は core にもあるが、market 層を自己完結させるため重複格納。

## シリーズと用途

| ティッカー | 内容 | 実測開始 | 用途 |
|---|---|---|---|
| `^VIX` | VIX指数 | 1990-01 | 水準＋急騰 |
| `^VIX3M` | VIX 3ヶ月 | 2006-07 | 期間構造 `^VIX/^VIX3M`>1＝ストレス |
| `HYG` | ハイイールド債ETF | 2007-04 | 信用スプレッド代理 |
| `JNK` | ハイイールド債ETF | 2007-12 | 信用（HYG確認） |
| `LQD` | 投資適格債ETF | 2002-07 | 信用（IG基準） |
| `IEI` | 3-7年米国債ETF | 2007-01 | HYGのデュレーション・ヘッジ |
| `IWM` | ラッセル2000 | 2000-05 | `IWM/SPY`＝リスク選好 |
| `SPY` | S&P500 ETF | 1993-01 | 基準 |

> 派生指標（VIX/VIX3M比・HYG/IEI比・IWM/SPY比等）は**しきい値チューニング前提のため保存せず**、
> raw シリーズのみ格納。計算は利用側。将来必要なら `market/risk/{year}.json` を別層で追加。

## スクリプト

| スクリプト | 用途 |
|---|---|
| `fetch_market_series.py` | Yahoo から 8 シリーズ取得（auto_adjust）→ `data/temp_market.json` |
| `build_market_by_year.py` | 年別統合ファイル + metadata を `data/market/r2/market/` に生成 |
| `upload_market_to_r2.py` | R2 へアップロード（過去年は不足時のみ／当年上書き／metadata常時、既定 dry-run） |

### 実行手順

```bash
# フル履歴（初回）
python scripts/market/fetch_market_series.py
python scripts/market/build_market_by_year.py
python scripts/market/upload_market_to_r2.py            # dry-run で計画確認
python scripts/market/upload_market_to_r2.py --execute  # R2 投入

# 期間指定（ドライラン/日次相当）
python scripts/market/fetch_market_series.py --start 2026-01-01
python scripts/market/build_market_by_year.py
python scripts/market/upload_market_to_r2.py --execute  # 当年ファイルを上書き更新
```

日次更新は当年ファイルの上書きで回る（core と同じ凍結流儀）。過去年は一度投入すれば凍結。
