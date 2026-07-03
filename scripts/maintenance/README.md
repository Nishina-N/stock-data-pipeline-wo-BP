# scripts/maintenance

日次パイプライン（`scripts/daily/`）とは別に、**R2 の棚卸し・欠損補充・廃止データ掃除**などを
手動または `workflow_dispatch` で実行するためのメンテナンス用スクリプト群。

いずれも `common/r2.py`（R2 クライアント）と `.env`（認証情報）を利用する。
破壊的・外部書込を伴うものは **既定 dry-run、`--execute` 等で初めて実書込** する安全設計。

## 現行の格納モデル（前提）

```
stocks/daily/core/{year}/{symbol}.json   … OHLCV + rs_percentile
scores/RS_scores/{sector,industry}/{year}.json
metadata/...
```

- individual RS は core の `rs_percentile` と重複するため **廃止**（scores へ出力しない）
- indicators / RRS / summary / BuyPressure 系統も **廃止**

---

## スクリプト一覧

### 棚卸し・診断（読み取り専用）

| スクリプト | 用途 |
|---|---|
| `check_r2_files.py` | R2 バケット全体をプレフィックス別に集計（件数・容量）。廃止系統が残っていれば警告。 |
| `diagnose_gap.py` | `core/{year}/{symbol}.json` の年別レコード数・日付レンジ・RS/volume 埋まり数を集計し、欠損期間を可視化。 |
| `verify_backfill.py` | 埋め戻し生成物（`data/backfill/...`）の RS 分布・[1,99] 収まり・年前半/後半の連続性を検証。 |

```bash
python scripts/maintenance/check_r2_files.py
python scripts/maintenance/diagnose_gap.py                 # サンプル銘柄で概況
python scripts/maintenance/diagnose_gap.py AAPL MSFT NVDA  # 指定銘柄を詳細表示
python scripts/maintenance/verify_backfill.py AAPL MSFT    # 生成後の検証
```

### 補充・掃除（書込・要 `--execute`）

| スクリプト | 用途 | 安全装置 |
|---|---|---|
| `backfill_gap_2023_2024.py` | 2023前半の価格欠損 + 2023全体/2024前半の RS 欠損を埋め戻す（下記詳細）。 | `--dry-run` / `--build`（ローカル生成のみ） / `--execute` / `--upload-only` |
| `backfill_market_symbols.py` | 主要指数・ETF の上場来 OHLCV を core に補充（欠けている年のみ）。 | 既定 dry-run、`--execute` で実書込 |
| `cleanup_deprecated_r2.py` | 廃止系統（indicators/RRS/summary/BuyPressure）のオブジェクトを R2 から削除。 | 既定 dry-run、`--execute` で実削除 |

---

## `backfill_gap_2023_2024.py` 詳細

### 背景（この欠損が起きた原因）

3 つの要因の複合：

1. **過去年ファイルの凍結** — `5_upload_to_r2.py` は過去年ファイルを「R2 に無ければ書く」方式で、
   一度作られた過去年は上書きしない。
2. **直近1000日窓** — `2_fetch_price_data.py` は Yahoo から直近1000日しか取得しない。
   パイプライン初回作成時（~2026-02）の窓の起点が **2023-05-22** だったため、
   2023-01..05 の価格行がそもそも書かれず truncated のまま凍結された。
3. **RS 出力窓500日** — `3_calculate_rs.py` は直近500日分の RS しか出力しないため、
   core への RS 埋め込みが **~2024-05 以降** までしか届かず、2023全体 + 2024前半の RS が欠損した。

結果：

| 年 | 症状 |
|---|---|
| 2023 | price/volume が 2023-05-22 以降のみ（前半欠損）、RS 全欠損。全市場で 2023 前半に行があるのは指数/ETF の18銘柄のみ。 |
| 2024 | price は完全だが RS が前半（〜5月）欠損。 |

### 補充方針（Yahoo 再取得を最小化）

1. R2 `core`（2022/2023/2024）から全銘柄の OHLCV を読む（RS の252日 lookback を賄い、既存行の保全にも使用）
2. **Yahoo 取得は不足分（2023-01-02〜05-19）だけ** 全銘柄ぶん
3. 本番（`3_calculate_rs.py`）と同一ロジックで RS を横断再計算
   （63/126/189/252日リターンを 0.4/0.2/0.2/0.2 加重 → percentile `rank*98+1`、`min_days=252`）
4. **マージ書き戻し（既存 OHLCV 行は保全）**：
   - 2023 = 既存行 + 取得した Jan–May 価格行 + 全行に RS 付与
   - 2024 = 既存 OHLCV はそのまま、**RS が空の行（Jan–May）だけ** 補充
5. アップロードは 2023/2024 のみ強制上書き

### 実行手順（推奨：ドライラン→ローカル生成→確認→アップロード）

```bash
# 1) 数銘柄でプラミング検証（RS絶対値は全銘柄実行時に確定）
python scripts/maintenance/backfill_gap_2023_2024.py --dry-run AAPL MSFT NVDA

# 2) 全ユニバースをローカル生成（R2未書込）。data/backfill/ に出力
python scripts/maintenance/backfill_gap_2023_2024.py --build

# 3) 生成物を検証
python scripts/maintenance/verify_backfill.py AAPL MSFT NVDA TSLA META

# 4) 問題なければ R2 へ強制上書き（生成済みを再計算せずアップロード）
python scripts/maintenance/backfill_gap_2023_2024.py --upload-only

# （2〜4を一括で行う場合）
python scripts/maintenance/backfill_gap_2023_2024.py --execute
```

### 注意点

- 2023-01-03 の1日だけ RS=None になる（252日 lookback の境界。実害なし）。
- 2023 以降の IPO 銘柄（ARM/CAVA/RDDT 等）は当時取引実体が無いため 2023 前半は補充されない（正常）。
- 再実行は冪等。既存の非空 RS・既存 OHLCV 行は保全され、欠損のみ埋める。

### 再発防止メモ

2023/2024 が完全化した後は、日次パイプラインの過去年保護により再 truncate は起きない。
ただし構造として「新年ファイルが初回に不完全なまま凍結される」余地は残るため、
恒久対策が必要なら **年末に前年ファイルの完全性チェック→不足なら backfill** を定型化するとよい。
