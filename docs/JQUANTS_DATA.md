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

### 🔴 台帳・当初プローブに載っていなかったエンドポイント

公式の仕様一覧（https://jpx-jquants.com/ja/spec）で判明。うち3つは台帳が
「V2パス未特定」として諦めていたもの。**エンドポイント一覧は台帳ではなく公式を見ること。**

| パス | 実開始 | 備考 |
|---|---|---|
| `/edinet/large-volume-shareholders` | 2021-07-01 | 大量保有報告。`TotalShsRatio`/`TotalShsRatioLast`/`ChgRsn` |
| `/edinet/major-shareholders` | 2016-06-03 | 大株主 |
| `/edinet/cross-shareholdings` | 2020-05-29 | 政策保有株式 |
| `/fins/earnings-date` | 2014-09-01 | **発表予定日の履歴**（`SchDate`/`PubDate`）。earnings-calendar とは別物 |
| `/bulk/list` `/bulk/get` | — | 月次 gzip CSV。下記 |

### /bulk で取得コストが桁違いに下がる

`/bulk/list?endpoint=...` が月次 gzip CSV の一覧を返し、`/bulk/get?key=...` が
署名付き URL を返す。日次 API を営業日ぶん叩く必要がない。

**225オプションは API 経由で約4時間のところ bulk で4分**（228ファイル・255MB）。

対応: options225 / futures / indices / short-sale-report / earnings-date / bars/daily ほか。
**EDINET 系は非対応**（"This endpoint is not available for csv download"）。

⚠️ bulk の内容が API と一致する保証はない（FMP で最新データ欠落の実績あり）ので、
`6_fetch_bulk.py --verify` が同じ日を日次 API でも引いて**件数と列**を突き合わせる。

🔴 **`/equities/bars/daily` は bulk が Adj* 15列を落としている**（API 44列 / bulk 29列）。
   AdjO/AdjC/AdjH/AdjL/AdjVo と前場(MAdj*)・後場(AAdj*)ぶん。
   **行数は一致するので件数比較だけでは気づけない。** この系統だけは日次 API で取る。
   （delisted_bars は API 経由で44列なので、bulk で取ると同じ名前空間に
     列構成の違う4本値が並ぶことになる）
   他の5系統（options225 / futures / indices / short-sale-report / earnings-date）は
   件数・列とも完全一致。

⚠️ `/indices/bars/daily/topix` は `indices` の `Code='0000'` と同一なので取らない
   （2016-09 の終値 20/20 一致を確認済み）。`date` パラメータも効かず全期間を返す。

⚠️ `/markets/short-sale-report` は `date` を受け付けず `disc_date`/`calc_date`/`code`。
検証時の日付パラメータは系統ごとに違う。

### 使えないもの

- `/equities/bars/minute`・`/equities/bars/daily/am` … 403（アドオン未購入）
- `/equities/earnings-calendar` … 200 だが**次の発表予定1件のみで履歴なし**。
  ただし **`/fins/earnings-date` には履歴がある**（別物）
- 株価ティック … V2 にパスが存在しない（`/equities/trades` は
  403「endpoint does not exist」）。**「パス未特定」ではなく「不在」で確定**

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

## R2 レイアウト（2026-08-16 投入済み・246オブジェクト 3,095MB・5,053万行）

| キー | 行数 | 実開始 | 内容 |
|---|---|---|---|
| `calendar.json` | 7,305 | 2008-01-01 | HolDiv 付き（2027-12-31まで） |
| `delisted_codes.json` | 1,478 | — | master から導出した廃止銘柄 |
| `master_monthly.parquet` | 790,889 | 2008-05-30 | 月末営業日の上場銘柄一覧 |
| `delisted_bars.parquet` | 2,686,931 | 2008-05-07 | 廃止銘柄の日次4本値（UL/LL/MktCap 付） |
| `fins_summary/{year}.parquet` | 364,080 | 2008-07-07 | **DiscDate/DiscTime = 実発表日時** |
| `fins_details/{year}.parquet` | 264,435 | 2009-01 | BS/PL/CF。FS は JSON 文字列 |
| `dividend/{year}.parquet` | 302,627 | 2013-01 | ExDate（権利落ち日）付き |
| `breakdown/{year}.parquet` | 10,982,410 | 2015-04-01 | 売買内訳（現物/信用新規/信用返済） |
| `short_ratio/{year}.parquet` | 138,176 | 2010-01-04 | **価格規制あり/なし**（33業種単位） |
| `margin_interest/{year}.parquet` | 2,733,428 | **2012-02-10** | 週末残高（**金曜のみ**）。制度/一般別 |
| `margin_alert/{year}.parquet` | 576,964 | 2008-05 | 日々公表。PubReason にフラグ |
| `investor_types.parquet` | 4,338 | 2008-01-04 | 投資部門別（週次・年分割なし） |
| `options225/{year}.parquet` | 12,837,206 | 2008-05-07 | 日経225オプション（bulk 取得） |
| `short_sale_report/{year}.parquet` | 1,562,921 | **2013-11-07** | 空売り残高報告（bulk 取得） |
| `indices/{year}.parquet` | 608,937 | 2008-05-07 | 指数4本値・152指数（bulk 取得） |
| `futures/{year}.parquet` | 301,789 | 2008-05-07 | 先物（bulk 取得） |
| `earnings_date/{year}.parquet` | 183,423 | **2014-09-01** | 発表**予定**日（bulk 取得） |
| `edinet_large/{year}.parquet` | 64,896 | **2021-07-01** | 大量保有報告 |
| `edinet_major/{year}.parquet` | 44,386 | **2016-06-03** | 大株主 |
| `edinet_cross/{year}.parquet` | 25,694 | **2020-05-29** | 政策保有株式 |
| `bars_daily/{year}.parquet` | 16,043,562 | 2008-05-07 | 現存銘柄の日次4本値（照合用・**API経由44列**） |

### 保存時の型の扱い

- **入れ子（dict/list）は JSON 文字列にする**。`/fins/details` の `FS` は
  125要素前後の辞書でキーが XBRL のラベル文字列。2025年単年で**のべ2,632種類**あり、
  列に展開すると巨大なスパースになる。`json.loads` で復元できる。
- **数値と文字列が混在する列は文字列に統一する**。`/fins/dividend` の `DivRate` 等は
  数値と `'-'`（該当なし）が混ざり、そのままでは pyarrow が落ちる。
  `'-'` を null に潰すと「該当なし」と「欠測」の区別が消えるため潰さない。
  利用側は `pd.to_numeric(errors='coerce')`（`DivRate` は 92.1% が数値）。

## 取得結果から分かったこと（研究側への申し送り）

### 1. 廃止率は定常でない — 3.36% の過去外挿は過大

master 月次スナップショットから実測した年率廃止率:

| 期間 | 年率 |
|---|---|
| 2008-2010 | 3.07 / 3.09 / 2.79% |
| 2014-2020 | 0.94〜2.03%（底） |
| 2024-2026 | 2.30 / 2.95 / 3.35%（再上昇） |
| **通期** | **2.08%** |

研究側が 2024-09〜2026-04 で測った 3.36% は**その期間としては正しい**が、
過去に外挿した「21年で 51.3%」は実測 **32.0%**（18.3年）に対し6割の過大。

### 2. 🔴 2013-07 に JASDAQ が合流している（東証・大証の現物市場統合）

```
2013-06  2,498銘柄  東証一部1,722 / 二部411 / マザーズ185   ← JASDAQ なし
2013-07  3,616銘柄  東証一部1,762 / JASDAQ 845 / 二部569
```

**2013-07 より前の master には JASDAQ が1銘柄も無い。**
当該期間の JASDAQ 銘柄のサバイバーシップは原理的に観測できず、
上の通期 2.08% / 累積 32.0% もこの不連続を跨いだ暫定値。
整合的な率が要るなら 2013-07 以降で切ること。

なお在籍が不連続なコード（＝コード再利用の疑い）は 5,921 中 **16件**のみで、
廃止件数の取りこぼし要因としては無視できる。

### 3. 🔴 A-2 の「価格規制あり/なし」は breakdown に無い

台帳は「breakdown で信用新規売りが価格規制あり/なしに分かれる＝51単元(5,100株)
規制を実測できる」としているが**誤り**。breakdown の16列は:

```
LongSellVa/LongBuyVa(現物)  ShrtNoMrgnVa(現物空売り)
MrgnSellNewVa/MrgnBuyNewVa(信用新規)  MrgnSellCloseVa/MrgnBuyCloseVa(信用返済)
```

価格規制の区分は `short-ratio` の `ShrtWithResVa` / `ShrtNoResVa` にしか無く、
しかも **33業種単位で銘柄別ではない**。MAXLOT 50 近似の検証は業種粒度が上限。
（参考: 2025年は価格規制ありが 77.4% = 419.8兆円 / 542.6兆円）

### 4. DocType の汚染は初期ほど重い

`/fins/summary` は決算発表以外も返る。`FinancialStatements` を含む型で絞らないと
業績予想修正を決算と取り違える。**その比率は単調に減少している**:

| 年 | 決算率 | 業績予想修正 | 配当予想修正 |
|---|---|---|---|
| 2008 | 64.7% | **32.4%** | 2.9% |
| 2009 | 63.3% | **32.4%** | 4.3% |
| 2013 | 72.4% | 23.9% | 3.7% |
| 2017 | 79.2% | 16.9% | 3.6% |
| 2021 | 80.6% | 16.8% | 2.3% |
| 2026 | 88.0% | 9.8% | 2.0% |
| **全期間** | **77.0%** | — | — |

研究側報告の 16% は概ね 2017-2018 の水準で、**2008-2009 はその倍**。
`earningsDate` 充足率が 17-39% と最も悪い 2008-2013 と重なるため、
**データが最も悪い期間で DocType フィルタの効きが最も大きい**。
`DocType` と `DiscTime` は R2 に保持済み（36.4万件で欠損ゼロ）。

### 5. 🔴 fins/details でも OCF の穴は埋まりきらない（開示制度の問題）

台帳 B-1 は「FCF/OCF の 71.6% ゼロ潰れ解消」を魅力に挙げるが、
**開示自体にキャッシュフロー計算書が付かない四半期が大半**（2025年で実測）:

| 四半期 | 件数 | OCF 被覆 |
|---|---|---|
| 1Q | 4,044 | **5.9%** |
| 2Q | 3,933 | 75.7% |
| 3Q | 4,060 | **6.2%** |
| FY | 4,392 | 92.6% |
| 全体 | | 45.9% |

日本の四半期開示では CF 計算書が 2Q と FY にしか付かないのが通例。
つまり FMP の「71.6% ゼロ潰れ」の相当部分は **FMP の欠陥ではなく制度**であり、
J-Quants に替えても 1Q/3Q は埋まらない。埋まるのは「2Q・FY で FMP が
落としていた分」だけ。OCF/FCF は四半期系列ではなく**年2回の観測**として扱うこと。

### 6. margin-interest は金曜のみ / 実開始は 2012-02-10

週末残高なので月〜木は 200 で 0 件しか返らない（2025-06-23〜26 は全て 0、27(金) で 4,264）。
全営業日を叩くと 8 割が空振りになるため friday モードで取得する（4,471 → 830 回）。
実データの開始は **2012-02-10**（2010-01-01 から 117 金曜ぶんは空）。

`ShrtVol`(売り残) が `ShrtStdVol`(制度信用) と `ShrtNegVol`(一般信用) に分解される。

### 7. margin-alert の PubReason で日々公表銘柄が直接特定できる

`PubReason` は入れ子で、`DailyPublication` / `Restricted` / `Monitoring` /
`RestrictedByJSF` / `PrecautionByJSF` / `UnclearOrSecOnAlert` のフラグを持つ。
台帳 B-5 が「価格乖離だけの粗いプロキシ（25日MA+30%乖離3日連続）で近似して止めた」
日々公表銘柄が、これで実測に置き換わる（2025年で 7,244 件が DailyPublication=1）。

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
  6_fetch_bulk.py            /bulk 経由の月次CSV取得と検証
  7_audit.py                 完全性監査（A日付被覆〜E値の一致）
  8_daily_update.py          日次差分の追記（Light プラン用・GitHub Actions）
  9_fetch_addon_bulk.py      分足・ティック（アドオン）の bulk 取得と parquet 化
```

1〜7 は**一回きりの履歴取得**。1日1ファイル / 1銘柄1ファイルで保存し、取得済みは
スキップする。数時間のジョブが中断しても再実行すれば続きから再開できる。
0件の日も空ファイルとして記録する（「未取得」と「元々データ無し」の区別のため）。

8 だけが定期実行で、ローカルに JSON を残さず R2 の parquet を直接
read-modify-write する。

## 分足・ティック（アドオン・2026-08-26〜）

Light プランに **分足/ティックのアドオン**を追加して取得した。
取得は `9_fetch_addon_bulk.py`、投入は既存の `5_upload_jquants_r2.py`。

### 🔴 契約窓は「直近2年のローリング」

2026-08-26 時点で `2024-08-26 ~ `。それより前の日付は 400 が返る:

```
{"message": "Your subscription covers the following dates: 2024-08-26 ~ ."}
```

**窓は前へ動く**。他の系統（2008年から取り切ってある）と違い、
**取らずに放置した古い月は二度と取れない**。定期的に新しい月を取り続けること。

🔴 **bulk の月次ファイルは契約窓より前の日も含んで返す**。窓の開始が
2024-08-26 なのに `..._202408.csv.gz` は **2024-08-01 から**入っていた
（分足 9,668,606行 / ティック16営業日ぶん）。API 単体では 400 で拒否される
日付が bulk では取れるということ。**窓の端の月は必ず bulk で取る**。

### エンドポイント

| 系統 | API | bulk | 列 |
|---|---|---|---|
| 分足 | `/equities/bars/minute` ✅ | ✅ | `Date,Time,Code,O,H,L,C,Vo,Va` |
| ティック | **無し**（403 "endpoint does not exist"） | ✅ | `Date,Code,Time,SessionDistinction,Price,TradingVolume,TransactionId` |

- 🔴 **ティックに API パスは存在しない**。`/equities/trades` は公式仕様に
  載っているが直接叩くと 403 で、`/bulk/list?endpoint=/equities/trades` は 200 を返す。
  **ティックは bulk 専用**。日次追記も bulk の `live/` から取る。
- 分足の API は `date=` だけで**全銘柄**が返る（1日 約45万行）。
  `code=` 単独だと契約窓の全期間が返る。`from`/`to` も効く。
- bulk のキーは2階層: 月次 `.../historical/{YYYY}/..._{YYYYMM}.csv.gz` と
  当月ぶんの日次 `.../live/..._{YYYYMMDD}.csv.gz`。
  月が締まると `live/` の日次が `historical/` の月次に畳まれる。
- `Time` の粒度は分足が `HH:MM`、ティックが `HH:MM:SS.ffffff`。
- レートはプラン上限とは独立に **60 req/分**。ただし投げるのは list/get だけで、
  実データは署名付き URL（認証不要）から落ちるので実質ネットワーク律速。

### 保存の粒度

規模が他系統と2桁違うため、`4_compact_to_parquet.py`（年次 pd.concat）には
載せずに専用スクリプトでストリーミング変換する。

| 系統 | 置き場所 | 粒度 |
|---|---|---|
| 分足 | R2 `jp/jquants/bars_minute/{YYYYMM}.parquet` | 月次 |
| ティック | **ローカルのみ** `data/jquants/_parquet/trades/{YYYY}/{YYYYMMDD}.parquet` | 日次（1日 約36MB） |

圧縮は zstd。ティックを月次にすると1枚 1GB 級になり、部分読み出しも
再取得もできなくなる。

### 🔴 ティックは R2 に上げない（2026-08-26 の運用方針）

全期間で約18GB あり、既存の `jp/jquants/`（3GB）を一気に6倍にするため、
**取得と parquet 化までをローカルで行い、R2 には載せない**。

`5_upload_jquants_r2.py` の `collect()` は `_parquet/**` を再帰で拾うので、
放っておくと次の実行で黙って載る。`EXCLUDE_BY_DEFAULT = {'trades'}` で
既定の収集から外してある。上げる判断をしたときだけ `--only trades` で
明示指定する（その場合は警告を出したうえで投入する）。

### 🔴 全列を文字列で読んでから数値列だけ戻す

bulk CSV の素朴な数値化はゼロ埋めの先頭0を落とす（`fins_summary` で
`FYE '0120' → 120` を踏んだのと同じ罠）。ここでは
`Code '13010'` / `SessionDistinction '01'` / `TransactionId '000000000008'` が該当。
`dtype=str` で読み、`O/H/L/C/Vo/Va`（分足）と `Price/TradingVolume`（ティック）
だけを `to_numeric` で戻している。

### 検証

- **分足**: 同じ日を bulk と API で引いて行数・列を突き合わせる
  （2026-08-26: 452,394行 / 452,394行、9列一致）。
- **ティック**: 突き合わせる API が無いので、**日次4本値の `Vo` と
  ティックの `TradingVolume` 合計を銘柄ごとに照合**する
  （2026-08-26: 4,217/4,217 銘柄、2025-08-14: 4,222/4,222 銘柄が完全一致）。
- **日付被覆**: カレンダーの営業日（`HolDiv` が `1`/`2`）と日次ファイルを突き合わせ、
  2024-08-26〜2026-08-26 の 488 営業日に**欠落なし**（＋窓より前の16営業日）。

### 取得実績（2026-08-26）

| 系統 | 期間 | 単位 | 行数 | サイズ |
|---|---|---|---|---|
| 分足 | 2024-08-01〜2026-08-26 | 25ヶ月 | 233,981,154 | 2,867MB（R2 投入済み） |
| ティック | 2024-08-01〜2026-08-26 | 504日 | **2,016,002,654** | 18GB（ローカルのみ） |

## 🔴 Light プランへのダウングレード（2026-08-16〜）

履歴を Premium で取り切ったあと Light に落とした。以後の日次更新は
`8_daily_update.py` を GitHub Actions（`.github/workflows/jquants-daily.yml`,
**UTC 07:40 = JST 16:40**、4本値確定の 16:30 から10分の余裕）で回す。

### Light で引ける / 引けない（2026-08-16 実測）

| 引ける | 403（Standard 以上） |
|---|---|
| `/markets/calendar` | `/fins/details` `/fins/dividend` |
| `/equities/master` | `/markets/breakdown` `/markets/short-ratio` |
| `/equities/bars/daily` | `/markets/short-sale-report` |
| `/fins/summary` | `/markets/margin-interest` `/markets/margin-alert` |
| `/fins/earnings-date` | `/indices/bars/daily` |
| `/equities/investor-types` | `/derivatives/bars/daily/*` |
| `/indices/bars/daily/topix` | `/edinet/*` |

403 側の R2 既存ファイルは**触らない**。プランを戻せば 1〜7 が取得済みの日を
スキップして続きから埋める。

### 🔴 Light は直近5年しか返さない

`calendar` は Light だと 2021-08〜 の 2,329 日しか返らない（R2 の
`calendar.json` は 7,305 日 = 2008-2027）。**素朴に上書きすると履歴が消える**。
`8_daily_update.py` の `update_calendar` は必ず Date でマージし、
マージ後に件数が減ったら例外にしている。`investor_types.parquet` /
`master_monthly.parquet` / `topix.parquet` も単一ファイルの積み上げなので追記のみ。

### 🔴 Light の 4本値は前場・後場が落ちる

`/equities/bars/daily` は **Premium 44列 → Light 18列**。差の26列は
前場(`M*`)・後場(`A*`)の四本値で、値が null になるのではなく**キーごと
応答から消える**。Premium 期間は `MO` 627,105 / 666,466 行（94%）埋まっていた。

R2 のファイル構成を壊さないため欠測で埋めて追記する（列が消えると研究側の
読み込みが壊れる）。**2026-08-15 以降の `M*`/`A*` は「欠測」であって
「その日は前場が無かった」ではない**。`PLAN_GATED_COLUMNS` に列挙してあり、
既知の欠落は INFO、想定外の列差は WARNING で出る。

`ExRT`（権利落ち率）はプラン差ではない。Premium でも 158/666,466 行しか
埋まっていない元々疎な列。

### 追記の安全弁

- `--lookback N`（既定10日）で遡って未取得の営業日だけを埋める。
  1回落ちても翌営業日の実行が自動で埋める。
- 応答が0件の日は**既存を残す**。API の一時的な欠落でデータを消さない。
- 年次ファイルは年ごとに読み書きするため、年初をまたいでも前年ぶんが壊れない。
  `{year}.parquet` が無ければ**前年の列・dtype を引き継いだ空フレームから作る**。
  1月最初の応答だけで列構成を決めると、その日たまたま全銘柄 null だった列が
  落ちて前年とスキーマがずれるため、必ず前年を土台にする。
  前年も無ければエラー終了（1〜5 のフルパスで作る）。
- 🔴 **欠測表現の混在**。`earnings_date` の R2 履歴は bulk CSV 由来で欠測が NaN、
  API(JSON) は空文字 `''` を返す（`SchDate` = 発表予定日が未定の行で実際に発生）。
  追記側を None に寄せて揃える（`EMPTY_AS_NULL`）。他の系統は履歴も API 由来で
  `''` に統一されているので変換しない。
- `concurrency: jquants-daily` で schedule と手動実行の同時走行を止める。
  read-modify-write なので並走すると片方の追記が失われる。

### 検証済み（2026-08-16）

R2 の 2026年ファイルから末尾3営業日を落とし、8 に再取得・追記させて元と比較:

```
bars_daily    666,466行 × 44列  一致（差分は既知の Light 欠落26列のみ）
fins_summary   13,381行 ×111列  全セル一致
earnings_date   8,945行 ×  7列  全セル一致
dtype も3系統とも一致
```

年またぎも同様に検証した。2026年ファイルが R2 に無い状態を作り、2025年の構成を
継いで 2026-01 の5営業日を取得させて、本物の 2026 ファイルと比較:

```
bars_daily     22,178行  列一致・dtype一致・想定外の差分なし
fins_summary      150行  同上
earnings_date     270行  同上
```
