# データ棚卸し（What we store & why）

最終更新: 2026-06-23

## 適用済みの変更（2026-06-23）

利用状況の決定を受けて、daily パイプラインを以下に整理（スクリプト縮小）した。

| 変更 | 内容 |
|------|------|
| RRS 全廃 | 計算・出力・アップロードを削除（`3_calculate_rs.py` から RRS 関数群を除去） |
| `*_raw` 廃止 | スコアは `rs_percentile` のみ（容量約半減） |
| indicators(#2) 廃止 | `2.5` は pkl→json（OHLCV のみ）変換に縮小。指標は OHLCV から利用側で再計算 |
| summary(#3) 廃止 | `6_export_summary.py` 削除、ワークフローから除外 |
| core(#1) | OHLCV + `rs_percentile` のみに |
| upload | core / scores(RS) / metadata のみアップロード |
| 保証銘柄 | 指数・主要ETF・セクターETF11種を最終CSVへ強制注入（下記） |

### 保証銘柄（必ず取得・保存）
`1_fetch_target_stocks.py` の `MARKET_SYMBOLS` で管理。フィルタで脱落させず最終CSVに注入する。
- 指数: `^GSPC`(S&P500), `^IXIC`(NASDAQ), `^DJI`(Dow), `^RUT`(Russell2000)
- ブロードETF: `SPY`, `QQQ`, `DIA`, `IWM`, `SMH`, `SOXX`
- セクターSPDR 11種: `XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC`
- これらは Sector/Industry を `N/A` とし、セクター/業種RSの集計には混ぜない（個別RS と core OHLCV としては保持）。

> 注意: R2上の旧データ（indicators/RRS_scores/summary/BuyPressure）は `scripts/maintenance/cleanup_deprecated_r2.py --execute` で削除済み。
> 各 core ファイル内の `*_raw`/`rrs_*` フィールドは履歴ファイルに残存（低優先のため未除去）。
> 旧R2オブジェクトの掃除・棚卸しは `scripts/maintenance/cleanup_deprecated_r2.py`（削除）/ `check_r2_files.py`（集計）で実施する。
> ※ 旧フルパイプライン（`1_〜5_*`）と `clear_r2*.py` / `delete_scores_years.py` は現モデルと非互換のため削除した。

> 以下は変更前の棚卸し記録（参照用）。

---


このドキュメントは「R2に実際に何を貯めているか」「どこで生成され、誰が使うか」「重複・過剰計算はどこか」を棚卸ししたものです。
削減・整理の意思決定の土台として使います。コードを変更する前のスナップショットです。

> メモ（2026-06-23 時点の利用状況ヒアリング結果）
> - **フロント側は最近どの系統もほぼ使っていない**（RS/RRSスコアは止めても可）。
> - **intraday（5分足） / fundamentals / indicators は使用中**。ただし indicators は中身を見て要否判断したい。

---

## 1. R2データセット一覧

| # | パス | 中身 | 粒度 | 概算ファイル数 | 生成元 | 更新頻度 | 利用状況 |
|---|------|------|------|----------------|--------|----------|----------|
| 1 | `stocks/daily/core/{year}/{sym}.json` | OHLCV + RS/RRS（raw・percentile） | 銘柄×年 | 約4,600×4年 ≈ 18,000 | `daily/4_export_to_json.py` | 毎営業日 | フロント未使用 |
| 2 | `stocks/daily/indicators/standard/{year}/{sym}.json` | SMA20/50/200, EMA21, RSI14, ATR14, VWAP | 銘柄×年 | ≈ 18,000 | `daily/4_export_to_json.py` | 毎営業日 | 使用（要中身精査） |
| 3 | `stocks/summary/{date}.json` | 全銘柄の銘柄/セクター/業種 RS・RRS を1日分まとめ | 日付 | 約500 | `daily/6_export_summary.py` | 毎営業日 | フロント未使用 |
| 4 | `scores/RS_scores/{individual,sector,industry}/{year}.json` | RSスコア（年別） | 年×3区分 | 少 | `daily/4_export_to_json.py` | 毎営業日 | フロント未使用 |
| 5 | `scores/RRS_scores/{individual,sector,industry}/{year}.json` | RRSスコア（年別） | 年×3区分 | 少 | `daily/4_export_to_json.py` | 毎営業日 | フロント未使用 |
| 6 | `stocks/intraday/5min/{year}/{month}/{sym}.json` | 5分足OHLCV（直近60日分） | 銘柄×月 | 多 | `intraday/2_export_to_json.py` | intradayワークフロー | 使用 |
| 7 | `stocks/fundamentals/{sym}.json` | 四半期財務（EPS/売上/純利益/CF/BPS/PSR/ROE、最大120Q） | 銘柄 | 約4,600 | `monthly/fetch_fundamentals.py` | 月次 | 使用 |
| 8 | `metadata/last-updated.json` | 最終更新情報 | 1 | 1 | `daily/4_export_to_json.py` | 毎営業日 | 補助 |

※ ファイル数は data_retention_days=1000（約4暦年）と銘柄数約4,600からの概算。

---

## 2. フィールド定義（主要データセット）

### #1 core
`ticker, name, sector, industry, data[]`
`data[]` 各要素: `date, open, high, low, close, volume, rs_raw, rs_percentile, rrs_raw, rrs_percentile`

### #2 indicators
`ticker, indicators[], data[]`
`data[]` 各要素: `date, sma20, sma50, sma200, ema21, rsi14, atr14, vwap`

### #3 summary
`date, count, stocks[]`
`stocks[]` 各要素: `date, symbol, name, sector, sector_rs, sector_rrs, industry, industry_rs, industry_rrs, rs, rrs`

### #4/#5 scores
`individual`: `date, ticker, sector, industry, *_raw, *_percentile, rank`
`sector`: `date, sector, *_raw, *_percentile, rank, stock_count`
`industry`: `date, industry, sector, *_raw, *_percentile, rank, stock_count`

### #7 fundamentals
`ticker, data[], lastUpdated`
`data[]` 各要素: `date, eps, epsDiluted, revenue, netIncome, freeCashFlow, operatingCashFlow, stockholdersEquity, bookValuePerShare, priceToSalesRatio, roe`

---

## 3. 重複・過剰計算マップ

### 🔴 重複A: 個別RS/RRSが3系統に重複保存
同じ「銘柄×日のRS/RRSパーセンタイル」が以下の**3か所**に格納されている。
- #1 core（各銘柄ファイル内）
- #4/#5 scores/individual（年別）
- #3 summary（日別）

→ フロント未使用が確定すれば、**#3・#4・#5 は丸ごと削除候補**。残すなら1系統で十分。

### 🔴 重複B: `*_raw` と `*_percentile` が同じ値
`daily/3_calculate_rs.py` の `save_results_json` で、`rs_raw` と `rs_percentile` の**両方にパーセンタイル値**を入れている（RRSも同様）。
```python
'rs_raw':        round(float(rs_value), 2),   # ← 実際はパーセンタイル
'rs_percentile': round(float(rs_value), 2),
```
→ `*_raw` は中身がパーセンタイルの重複コピー。全スコア系統で容量が無駄に倍化。**`*_raw` フィールドは削除可**（または本来の生値を入れる）。

### 🟠 過剰C: indicators(#2)はcore(#1)のOHLCVから再計算可能
SMA/EMA/RSI/ATR はOHLCVがあればクライアント側で算出できる。別系統で約18,000ファイルを毎日生成・保持する必然性は低い。
→ 「サーバ計算済みを配る」運用を続けるか、「OHLCVだけ配ってクライアント計算」に寄せるかの設計判断。

### 🟠 過剰D: 毎日500日分を再計算・現在年を全再アップロード
日次で「1000日取得 → 全指標 → 直近500日分スコア → 現在年の全銘柄ファイル再生成・再アップロード（force overwrite）」を実行。
日々新規なのは最新1営業日のみ。計算・アップロードの大半は不変データの焼き直し。
→ 増分更新（最新日のみ追記）への変更余地が大きい。

---

## 4. indicators 各指標の評価（中身判断用）

`daily/2.5_add_indicators.py` の実装ベース。

| 指標 | 実装 | 評価 |
|------|------|------|
| sma20/50/200 | `close.rolling(n).mean()` | 妥当。標準的。 |
| ema21 | `close.ewm(span=21, adjust=False).mean()` | 妥当。 |
| rsi14 | gain/loss の単純移動平均ベース | 動作するが Wilder平滑化ではなくSMAベース。一般的なRSIと微差あり。 |
| atr14 | TRのrolling平均（SMAベース） | 同上。Wilderではないが概ね妥当。 |
| vwap | **1000日通算の cumsum** で算出 | ⚠ **要修正/削除候補**。日中リセットなしの通算VWAPは指標として意味が薄い。日足データに対する「当日VWAP」は本来 high/low/close の代表値に近く冗長。 |

判断の目安:
- **残す価値が高い**: sma群, ema21（トレンド系で素直に使える）
- **残してよいが要注意**: rsi14, atr14（計算方式が一般的なWilder式と違う点を許容できるか）
- **削除/修正推奨**: vwap（日足では実質無意味な計算）

---

## 5. 削減候補（優先度順）

利用状況ヒアリング（フロント未使用、intraday/fundamentals/indicators は使用）を反映。

| 優先 | 対象 | アクション | 効果 |
|------|------|-----------|------|
| 高 | #3 summary | フロント未使用なら生成停止（`6_export_summary` をワークフローから外す） | 約500ファイル/不変データの日次再生成を削減 |
| 高 | `*_raw` フィールド | 全スコア出力から削除（重複B） | 全スコア系統の容量を概ね半減 |
| 中 | #4/#5 scores | 残す系統を1つに集約、他は削除 | 重複A解消 |
| 中 | #1 core の RS/RRS | フロント未使用なら core はOHLCVのみに戻す検討 | core容量・計算削減 |
| 中 | indicators vwap | 削除または当日リセット実装に修正 | バグ/無駄の解消 |
| 低 | 過剰D（日次全再計算） | 増分更新へ段階移行 | ランタイム/転送量の継続的削減 |

> 注意: いずれも「フロント/利用側が本当に読んでいないか」を最終確認してから削除すること。
> 復旧コスト: scores/summary は再計算で再生成可能。core/indicators も価格データから再構築可能。

---

## 6. 確定タスク（次アクション候補）

- [ ] フロント側コードで参照しているR2パスを grep し、未使用系統を確証する
- [ ] 重複B（`*_raw`）の削除可否を決める
- [ ] summary(#3) の生成停止可否を決める
- [ ] indicators の vwap を「削除」か「当日VWAPへ修正」か決める
