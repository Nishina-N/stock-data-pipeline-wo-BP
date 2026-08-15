# J-Quants (V2) 取得仕様

Premium 契約下で 2026-08-15 に実測した内容。**推測ではなく全て API を叩いて確認した値**。
研究側の台帳（`momentum_trade/markets/jp/docs/JQuants取得候補データ_ABCランク.md`）と
食い違う点は本書が新しい。

## 認証

V1 は 410 で完全終了。V2 はトークン取得エンドポイントが廃止され、ダッシュボード発行の
API キーを `x-api-key` ヘッダに載せる方式になった。

- ベース: `https://api.jquants.com/v2`
- `.env` のキー名: `JQUANTS_API_KEY`
- 🔴 キーがヘッダに直接載るので、**ログ・例外文字列に混ぜないこと**
  （`_jq_client.Client._headers()` の戻り値は print しない）

## 🔴 データの実下限は 2008-05-07（契約窓ではない）

契約が返すのは `2006-08-15 ~`（＝今日から20年）だが、これは**サブスク窓**であって
データの実在範囲ではない。株価は 2008-05-07 が下限:

```
bars/daily  date=2008-04-30 → 0件
bars/daily  date=2008-05-07 → 2,494件
```

つまり利用できるのは **18.3年**。in-sample 前半の **2005-01〜2008-04（3.3年）は埋まらない**。

契約窓（2006-08）の方がデータ下限（2008-05）より古いので、**ローリング窓はいま制約に
なっていない**。効き始めるのは 2028年5月頃。

## 🔴 `master?date=` は下限より前を指定すると黙って 2008-05-07 を返す

エラーではなく **200 が返る**:

```
master?date=2006-08-15 → n=2,494  レコードの Date列 = "2008-05-07"
master?date=2008-05-07 → n=2,494  Code集合は完全一致（差分 0）
```

そのまま貯めると「2006年に上場していた」という**存在しない記録を捏造する**。
レコードの `Date` が要求日と一致するかで検出できるので、
`1_fetch_calendar_master.py` は不一致を破棄する。

## 取引カレンダーの `HolDiv`

`/markets/calendar` は 2008-01-01〜2027-12-31 の 7,305 件を1回で返す（Free でも可）。

| HolDiv | 意味 | 株式の立会 | 件数 |
|---|---|---|---|
| `1` | 営業日 | あり | 4,886 |
| `2` | 東証半日立会 | **あり**（2008-12-30 / 2009-01-05 とも 2,489銘柄） | 3 |
| `3` | 祝日取引日 | **なし**（2022-09-23 等いずれも bars/daily n=0。デリバティブのみ） | 67 |
| `0` | 非営業日 | なし | 2,349 |

`3` を営業日に含めると全系統で 67日ぶんの空振り呼び出しが出る。
営業日判定は `TRADING_HOLDIV = {'1', '2'}`。

## 系統ごとの実開始年（実測マトリクス）

各年の同一営業日（金曜）で件数を測った結果。

| 系統 | V2 パス | 実開始 | 1日あたり件数 |
|---|---|---|---|
| 上場銘柄一覧 | `/equities/master` | 2008-05 | 2,494 → 4,443 |
| 株価4本値 | `/equities/bars/daily` | 2008-05 | 2,494 → 4,443 |
| 財務情報 | `/fins/summary` | 2008-08 | 30〜1,000（決算期集中） |
| 財務諸表詳細 | `/fins/details` | 2010 | 10〜30 |
| 配当金情報 | `/fins/dividend` | 2013 | 30〜60 |
| **売買内訳** | `/markets/breakdown` | **2015-04-01** | 3,600〜4,100 |
| 信用週末残高 | `/markets/margin-interest` | 2013 | 4,200（金曜のみ） |
| 日々公表信用残高 | `/markets/margin-alert` | 2008 | 30〜250 |
| 業種別空売り比率 | `/markets/short-ratio` | 2010 | 34（33業種+計で固定） |
| 空売り残高報告 | `/markets/short-sale-report` | 2015 | 240〜800 |
| 投資部門別 | `/equities/investor-types` | — | 週次・ページング有 |
| 指数4本値 | `/indices/bars/daily` | 2008 | 44 → 152 |
| 225オプション | `/derivatives/bars/daily/options/225` | 2008 | 264 → 4,868 |
| 先物 | `/derivatives/bars/daily/futures` | 2008 | 21 → 103 |

⚠️ **売買内訳(A-2)は 2015-04-01 始まり＝11.4年**。台帳の「20年・日次・全銘柄」は誤り。
in-sample 前半 2008-2014 には掛からない。
2015-01〜03 はエラーではなく **200 で 0 件**が返るので、開始年の探索は件数で見ること。

### 使えないもの

- `/equities/bars/minute`・`/equities/bars/daily/am` … 403（アドオン未購入）
- `/equities/earnings-calendar` … 200 だが**次の発表予定1件のみで履歴なし**。研究には使えない
- 株価ティック … V2 にパスが存在しない（`/equities/trades` 等すべて不在）

## レート制限（公式仕様）

出典: https://jpx-jquants.com/ja/spec/rate-limits

**プラン別（アカウント全体・リクエスト/分）**

| Free | Light | Standard | **Premium** |
|---|---|---|---|
| 5 | 60 | 120 | **500** |

**エンドポイント個別（プランに関わらず適用・リクエスト/分）**

| エンドポイント | 上限 |
|---|---|
| `/v2/fins/summary` | 60 |
| `/v2/fins/details` | 60 |
| 分足・ティック（アドオン） | 60 |
| TDnet（アドオン） | 100 |

超過すると 429。**大幅超過を続けると5分程度アクセスが完全遮断される**ため、
上限には張り付かせない。Retry-After ヘッダは仕様に記載が無い。

🔴 **プランを変えたら過去の実測値を捨てること。**
「master は間隔6秒でも5回目に 429」という当方の実測メモは **Free 時代のもの**で、
Free は 5 req/分だから 6秒間隔(=10 req/分)なら 429 になって当然だった。
Premium ではこの経験則は成り立たず、100倍の余裕がある。

配分は `scripts/jp/jquants/_jq_rates.py` に一元化し、起動時に
`check_budget()` が合計をプラン上限と突き合わせる。

| ジョブ | レート |
|---|---|
| `fins_summary` | 57/分（個別上限60に margin） |
| `breakdown` / `delisted_bars` / `master` | 各 120/分 |
| **合計** | **417/分 < 500** |

`_jq_client.Client` は `min_interval` で間隔を強制し、429 は指数バックオフ
（遮断5分を待ち切れるよう上限 360 秒）で待つ。

## コード体系

`Code` は**5桁**で返る（4桁 + 末尾 `0`）。研究側パネルは4桁なので突合は `Code[:4]`。

```
master Code 例: ['13010', '13050', '13060', ...]   桁数分布 {5}   末尾0の割合 0.999
```

末尾が `0` でない 0.1% は `130A` のような英数字コード（`130A0`）。

## パラメータの探り方（★再利用可能）

必須パラメータが分からないときは、パラメータ無しで叩くと **400 の本文が教えてくれる**:

```
/markets/short-sale-report -> 400 {"message": "This API requires at least 1 parameter
                                    as follows; 'code','disc_date','calc_date'."}
```

契約範囲外の日付も同様に本文で分かる:

```
{"message": "Your subscription covers the following dates: 2006-08-15 ~ ."}
```

## R2 レイアウト

```
jp/jquants/calendar.json                取引カレンダー（HolDiv 付き）
jp/jquants/delisted_codes.json          master から導出した廃止銘柄一覧
jp/jquants/master_monthly.parquet       月末営業日時点の上場銘柄一覧（積み上げ）
jp/jquants/delisted_bars.parquet        廃止銘柄の日次4本値
jp/jquants/fins_summary/{year}.parquet  財務情報（DiscDate/DiscTime = 実発表日時）
jp/jquants/breakdown/{year}.parquet     売買内訳
```

## スクリプト

```
scripts/jp/jquants/
  _jq_client.py              認証・ページング・バックオフ
  _jq_bydate.py              日付単位で引く系統の共通ロジック
  1_fetch_calendar_master.py カレンダー + master月次 + 廃止銘柄の導出
  2_fetch_delisted_bars.py   廃止銘柄の日次4本値（1銘柄1ファイル）
  3_fetch_bydate_series.py   fins_summary / breakdown（1営業日1ファイル）
  4_compact_to_parquet.py    JSON → 年次 parquet
  5_upload_jquants_r2.py     R2 投入（既定ドライラン・--execute で実投入）
```

取得は**1日1ファイル / 1銘柄1ファイル**で保存し、取得済みはスキップする。
数時間のジョブが中断しても再実行すれば続きから再開できる。
0件の日も空ファイルとして記録する（「未取得」と「元々データ無し」の区別のため）。

定期実行はしていない。一回きりの履歴取得として設計してある。
