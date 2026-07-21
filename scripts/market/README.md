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
  "tickers": ["^VIX","^VIX3M","HYG","JNK","LQD","IEI","IWM","SPY",
              "HG=F","GC=F","CL=F","DX-Y.NYB","TIP","IEF","DBC","DBB"],
  "data": {
    "2024-08-05": {
      "^VIX": {"open":23.4,"high":65.7,"low":23.4,"close":38.6,"volume":null},
      "HG=F": {"open":4.03,"high":4.10,"low":4.01,"close":4.06,"volume":...},
      "...":  "..."
    }
  }
}
```

- **統合・年別**を採用（銘柄別ではなく）。リスク計算で全シリーズを 1 ファイルで日付整列でき、
  `^` / `=F` / `.NYB` を含むティッカーも JSON キーなので扱える。
- カバレッジが揃わない年はそのティッカーのキーが欠落（日付行自体は他シリーズで存在）。
  例: 1971=`DX-Y.NYB`のみ、1990=+`^VIX`、1993=+SPY、2007=信用系まで、以降は全16。
- **auto_adjust 済み終値**。比率（HYG/IEI 等）はトータルリターン的に adjusted が適切。
- SPY/IWM は core にもあるが、market 層を自己完結させるため重複格納。

## シリーズと用途

### リスク制御（VIX / 信用 / リスク選好）

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

### マクロ / コモディティ（セクターローテ・景気/金利感応）

| ティッカー | 内容 | 実測開始 | 用途 |
|---|---|---|---|
| `HG=F` | 銅先物 | 2000-08 | 景気敏感（`HG=F/GC=F`＝銅/金比） |
| `GC=F` | 金先物 | 2000-08 | 逃避・実質金利（銅/金比） |
| `CL=F` | 原油先物 | 2000-08 | エネルギー業種・原油トレンド |
| `DX-Y.NYB` | ドル指数（ICE） | 1971-01 | 資源・多国籍、DXYトレンド |
| `TIP` | TIPS ETF | 2003-12 | 実質金利・期待インフレ（vs `IEF`） |
| `IEF` | 7-10年米国債ETF | 2002-07 | ブレークイーブンの対（`IEF`−`TIP`相当） |
| `DBC` | 広義コモディティETF | 2006-02 | 資源業種全般 |
| `DBB` | 基本金属ETF | 2007-01 | 基本金属 |

### 米金利（2y/10y/30y）

| ティッカー | 内容 | 出典 | 実測開始 |
|---|---|---|---|
| `UST2Y` | 米国債2年利回り(%) | FMP `treasury-rates`（`fmp_treasury_rates`） | 1990-01 |
| `UST10Y` | 米国債10年利回り(%) | 同上 | 1990-01 |
| `UST30Y` | 米国債30年利回り(%) | 同上 | 1990-01（発行休止期間はデータ欠落あり） |

- Yahoo (`^TNX`等) は履歴を返さないため対象外だったが、FMP stable に
  `treasury-rates` エンドポイントがあることを2026-07-21に確認（1990-01-02〜の日次フル履歴）。
  1リクエスト約60日分の制限があるため `fetch_us_rates.py` で日付範囲を分割取得する
- JGB10Yと同様、利回り(%)を `open=high=low=close=利回り, volume=null` の疑似OHLCVとして格納
- 曲線傾き（10y−2y）等の派生指標は他シリーズ同様に保存せず利用側で計算

### JP マクロ（レジーム・為替・金利）

| ティッカー | 内容 | 出典 | 実測開始 | 用途 |
|---|---|---|---|---|
| `USDJPY=X` | ドル円 | Yahoo Finance | 1996-10 | 円建て市場の通貨レジーム |
| `JGB10Y` | 日本国債10年物利回り(%) | 財務省公式CSV（`mof_jgbcm`） | 1986-07 | JP金利レジーム |

- `JGB10Y` は Yahoo に存在しないため財務省「国債金利情報」CSV
  (`jgbcm_all.csv`、和暦・昭和49年(1974)〜)から取得。10年物の実測開始は1986-07
  （それ以前は10年物ベンチマーク自体が無い）。利回り(%)を疑似OHLCVとして
  `open=high=low=close=利回り`、`volume=null` で格納（他シリーズと形式を揃えるため）。
- `metadata.json` の各シリーズに `source` フィールドを追加（既定 `yahoo_finance`、
  JGB10Yのみ `mof_jgbcm`）。
- **日経VI（日経平均ボラティリティー・インデックス）はペンディング**：公式無料提供は
  直近3年(日次)/10年(月次)のみで、長期日次フル履歴を無料・無認証で取得できるソースが
  無いため見送り（2026-07時点）。

> 派生指標（VIX/VIX3M比・銅/金比・HYG/IEI比・IWM/SPY比等）は**しきい値チューニング前提のため
> 保存せず**、raw シリーズのみ格納。計算は利用側。

## スクリプト

| スクリプト | 用途 |
|---|---|
| `fetch_market_series.py` | Yahoo から取得（auto_adjust）→ `data/temp_market.json`。`--only`/`--start`/`--end`/`--strict`（劣化検知） |
| `fetch_jp_macro_jgb.py` | 財務省CSVから JGB10Y 取得 → `data/temp_market.json`（他と同じ形式） |
| `fetch_us_rates.py` | FMP `treasury-rates` から UST2Y/10Y/30Y 取得（日付範囲分割）→ `data/temp_market.json` |
| `build_market_by_year.py` | 年別統合ファイル + metadata を生成。`--merge`（既存R2に取得ティッカーを重ねる） |
| `upload_market_to_r2.py` | R2 へアップロード（過去年は不足時のみ／当年上書き／metadata常時、既定 dry-run）。`--force-past`（過去年も上書き） |

### 実行手順

```bash
# フル履歴（初回・全シリーズ新規）
python scripts/market/fetch_market_series.py --strict
python scripts/market/build_market_by_year.py
python scripts/market/upload_market_to_r2.py            # dry-run で計画確認
python scripts/market/upload_market_to_r2.py --execute  # R2 投入

# シリーズ追加（既存を壊さずマージ）
python scripts/market/fetch_market_series.py --only "HG=F,GC=F,CL=F" --strict
python scripts/market/build_market_by_year.py --merge   # 既存R2ファイルに重ねる
python scripts/market/upload_market_to_r2.py --force-past --execute  # 既存年も上書きして反映

# 日次更新（当年のみ）
python scripts/market/fetch_market_series.py --start 2026-01-01
python scripts/market/build_market_by_year.py --merge
python scripts/market/upload_market_to_r2.py --execute
```

### 取得の安全弁（重要）

`^VIX3M` 等は Yahoo が稀に「最新1行」しか返さない断続障害がある。これを気付かず
`--force-past` で再投入すると**既存の全年からそのシリーズが潰れる**。防止のため：

- `fetch --strict`：空 or 行数極小（`--min-rows`、既定100）のシリーズがあれば**失敗**して停止
- シリーズ追加時は `--only` で対象だけ取得 → `build --merge` で**既存シリーズに触れない**

日次更新は当年ファイルの上書きで回る（core と同じ凍結流儀）。過去年は一度投入すれば凍結。
