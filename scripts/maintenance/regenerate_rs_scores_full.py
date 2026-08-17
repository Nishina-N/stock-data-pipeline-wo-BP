"""regenerate_rs_scores_full.py

`scores/RS_scores/{sector,industry}/{year}.json` を **全期間** 現行定義で作り直す。

## なぜ必要か（2026-08-17 判明）

R2 の RS_scores は **2024-01-02 を境に2つの定義が連結されている**。

    1988-2023 (2026-02 生成)   rs_raw あり / stock_count 日次変動 /
                               industry の1日あたり群数 145〜149（日次変動）
    2024-2026 (2026-08 復旧)   rs_raw なし / stock_count 固定 /
                               industry の1日あたり群数 151（固定）

industry RS は日次クロスセクションの `rank(pct=True)*98+1` なので、
**母数が変われば値そのものが変わる**（percentile の刻みが 0.12〜0.15 → 0.650）。
sector も刻みは 8.910 で不変だが、研究側の独立再構成との順位相関が
旧 0.56〜0.78 / 新 0.86、1日順位変化が旧 0.66〜0.92 / 新 0.33〜0.37 で、
**旧側は個別銘柄RSに存在しない速さで動いていた**ことが確認された。

正しいのは **2024+ 側（現行 3_calculate_rs.py と一致）**。よって過去を揃える。

## 定義（現行 scripts/daily/3_calculate_rs.py と同一）

    1. 個別 rs_percentile は core から読む（再計算しない）
    2. グループ生値 = Σ(rs_percentile × w) / Σw   （w = close×volume）
       - rs_percentile が無い銘柄は分子・分母とも除外
       - **Σw == 0（該当銘柄0件）の群はその日 NaN → 順位付けに参加しない**
    3. 日次クロスセクション percentile = rank(pct=True) × 98 + 1
       - NaN は rank が無視するので、母数はその日の有効群数になる
    4. rank = その日の「自分より大きい値の個数 + 1」
    5. rs_raw は出力しない（現行仕様）

🔴 **一括・原子的に実施すること。** 年をまたいで新旧が混在する状態こそが実害の本体
   だった。`--execute` は指定年を全部生成し終えてからまとめて上げる。

使い方:
  python scripts/maintenance/regenerate_rs_scores_full.py --years 2024 --build
  python scripts/maintenance/regenerate_rs_scores_full.py --years 2024 --compare-r2
  python scripts/maintenance/regenerate_rs_scores_full.py --years 1988-2026 --build
  python scripts/maintenance/regenerate_rs_scores_full.py --years 1988-2026 --execute
"""
import os
import sys
import json
import logging
import argparse
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from common.symbols import load_symbols_info

from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = 'data'

# 市場ごとの置き場。**定義（build_year）は共有する**。
# 別スクリプトに分けると必ずまた乖離するので、ここだけを切り替える。
MARKETS = {
    'us': {
        'core':     'stocks/daily/core',
        'scores':   'scores/RS_scores',
        'universe': 'metadata/target_stocks_latest.csv',
        'snapshot': 'metadata/snapshots/target_stocks_{stamp}.csv',
        'out':      os.path.join(DATA_FOLDER, 'regen_rs_scores'),
        'csv':      os.path.join(DATA_FOLDER, 'target_stocks_latest.csv'),
    },
    'jp': {
        'core':     'jp/stocks/daily/core',
        'scores':   'jp/scores/RS_scores',
        'universe': 'jp/metadata/target_stocks_jp_latest.csv',
        'snapshot': 'jp/metadata/snapshots/target_stocks_jp_{stamp}.csv',
        'out':      os.path.join(DATA_FOLDER, 'regen_rs_scores_jp'),
        'csv':      os.path.join(DATA_FOLDER, 'target_stocks_jp_latest.csv'),
    },
}
M = MARKETS['us']          # main() が --market で差し替える
TARGET_STOCKS_CSV = M['csv']
OUT_ROOT = M['out']
CORE_PREFIX = M['core']
SCORES_PREFIX = M['scores']

MAX_READ_WORKERS = 24

# --weight-mode latest 用（旧 production 互換）に重みを取る年。
# 🔴 latest は歴史日付に将来の売買代金を当てる look-ahead。既定は pointintime。
WEIGHT_YEARS = [2024, 2025, 2026]


def parse_years(spec):
    out = []
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-')
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def download_universe(bucket):
    """現在のユニバース CSV を取得して symbols_info を作る。

    🔴 分類（symbol → sector/industry）は**現在のスナップショット**であり、
    時点対応ではない。歴史日付にも現在の分類を当てる。これは production と
    同じ扱いで、今回の変更で新たに増える look-ahead ではない。
    """
    os.makedirs(DATA_FOLDER, exist_ok=True)
    s3 = create_s3_client()
    obj = s3.get_object(Bucket=bucket, Key=M['universe'])
    with open(TARGET_STOCKS_CSV, 'wb') as f:
        f.write(obj['Body'].read())
    if M is MARKETS['jp']:
        # JP の CSV は列名が Symbol/Sector/Industry で US と違う。
        # production (scripts/jp/2_calculate_jp_rs.py) と同じ読み方をする
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'jp'))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            '_jprs', os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), 'jp', '2_calculate_jp_rs.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.load_symbols_info_jp(TARGET_STOCKS_CSV)
    return load_symbols_info(TARGET_STOCKS_CSV)


def read_core(s3, bucket, year, symbol):
    key = f'{CORE_PREFIX}/{year}/{symbol}.json'
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
    except Exception:
        return None      # その年に上場していない銘柄は 404。正常系


def load_year(symbols, bucket, year):
    """{symbol: {date: rs_percentile}} をその年ぶんだけ読む。

    年ごとに読んで年ごとに捨てるので、39年ぶんでもメモリは1年ぶんで収まる。
    """
    per_symbol = {}

    def _load(sym):
        s3 = create_s3_client()
        try:
            data = read_core(s3, bucket, year, sym)
            if not data:
                return sym, None
            rows = {}
            for r in data.get('data', []):
                v = r.get('rs_percentile')
                if v is not None:
                    # 時点重み用に close/volume も持つ（1988年から全行そろっている）
                    rows[r['date']] = (v, r.get('close'), r.get('volume'))
            return sym, (rows or None)
        finally:
            s3.close()

    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        futs = [ex.submit(_load, s) for s in symbols]
        done = 0
        for fut in as_completed(futs):
            sym, rows = fut.result()
            if rows:
                per_symbol[sym] = rows
            done += 1
            if done % 2000 == 0:
                logging.info(f'    read {done}/{len(symbols)}')
    return per_symbol


def load_weights(symbols, bucket):
    """重み（最新日の close×volume）。WEIGHT_YEARS を新しい順に探す。"""
    weights = {}

    def _load(sym):
        # 🔴 recover_rs_scores_2024_2026.py の latest_weight と**厳密に同じ**手順。
        # WEIGHT_YEARS 全体を通した最大日付を1つ選び、その日の close×volume を取る。
        # 「新しい年から探して最初に見つかったものを使う」だと、最終日の close/volume が
        # 欠けている銘柄で前年の値を拾ってしまい、復旧済みの 2024-2026 と食い違う
        # （実測: sector の順位が 49% で入れ替わった）。
        s3 = create_s3_client()
        try:
            last_date = last_close = last_volume = None
            for y in WEIGHT_YEARS:
                data = read_core(s3, bucket, y, sym)
                if not data:
                    continue
                for r in data.get('data', []):
                    d = r['date']
                    if last_date is None or d > last_date:
                        last_date = d
                        last_close, last_volume = r.get('close'), r.get('volume')
            if last_date is None:
                return sym, None          # データ皆無。重み表に入れない
            if last_close is None or last_volume is None:
                return sym, 1
            return sym, last_close * last_volume
        finally:
            s3.close()

    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        for fut in as_completed([ex.submit(_load, s) for s in symbols]):
            sym, w = fut.result()
            if w is not None:
                weights[sym] = w
    return weights



# ---------------------------------------------------------------------------
# 時点対応の分類（JP のみ）
# ---------------------------------------------------------------------------
# 🔴 銘柄の sector/industry は事業転換で実際に変わる。既定では**現在の**
#    ユニバースCSVを全歴史に当てており、これは look-ahead。
#    JP は J-Quants の月次マスタ（jp/jquants/master_monthly.parquet,
#    2008-05〜, 220スナップショット）に当時の S17/S33 があるので、
#    --classification pit でその日以前の直近スナップショットを使える。
#    US には同等の履歴が存在しない（core・CSV・FMP いずれも現在値）。
JQ_MASTER_KEY = 'jp/jquants/master_monthly.parquet'

# master のラベルは現行CSVと表記が違う。**群のキーを変えないため**正規化する
# （半角中黒 '･' → '・' のうえ、下の2つだけ語自体が異なる）。
# 正規化後は現行CSVと 100.00% 一致することを確認済み。
PIT_LABEL_FIX = {
    'sector':   {'電気・ガス': '電力・ガス'},
    'industry': {'証券・商品先物取引業': '証券、商品先物取引業'},
}
# ETF・投資信託のバケット。現行CSVの17/33分類には無いので群に含めない
PIT_EXCLUDE = {'その他'}


def load_pit_classification(bucket):
    """{snapshot_date: {code4: {'sector':.., 'industry':..}}} を返す。"""
    import io
    raw = create_s3_client().get_object(Bucket=bucket, Key=JQ_MASTER_KEY)['Body'].read()
    m = pd.read_parquet(io.BytesIO(raw))[['Date', 'Code', 'S17Nm', 'S33Nm']].dropna()
    m['code4'] = m['Code'].astype(str).str[:4]
    for col, key in (('S17Nm', 'sector'), ('S33Nm', 'industry')):
        m[key] = (m[col].str.replace('･', '・', regex=False)
                  .replace(PIT_LABEL_FIX[key]))
    out = {}
    for date, g in m.groupby('Date'):
        out[date] = {r.code4: {'sector': r.sector, 'industry': r.industry}
                     for r in g.itertuples()}
    logging.info(f'時点分類: {len(out)} スナップショット '
                 f'{min(out)} .. {max(out)}')
    return out


def segments_for(dates, snapshots):
    """営業日リストを、適用スナップショットごとの区間に分ける。

    as-of: その日**以前**で最も新しいスナップショットを使う。
    🔴 最古スナップショット(2008-05-30)より前の日は、最古で代用するしかない。
       JP の RS は 2004 から始まるので 2004-01〜2008-04 は時点対応にならない。
       ここを黙って現在分類にすると誤差の性質が年で変わるため、最古で固定する。
    """
    import bisect
    snaps = sorted(snapshots)
    out = defaultdict(list)
    for d in sorted(dates):
        d = str(d)[:10]
        # bisect_right - 1 = その日以前で最も新しいスナップショット。
        # 🔴 走査位置 i を使い回す実装だと、日付が str と Timestamp で
        #    混ざったときに比較が壊れて全日が最古に落ちる（2004年が
        #    248日→8日になった）。毎回二分探索する。
        k = bisect.bisect_right(snaps, d) - 1
        out[snaps[max(k, 0)]].append(d)
    return out


def build_year(per_symbol, weights, symbols_info, group_key, weight_mode,
               pit=None):
    """1年ぶんのレコードを作る。戻り値: (records, 診断dict)"""
    group_symbols = defaultdict(list)
    for sym in per_symbol:
        info = symbols_info.get(sym)
        if not info:
            continue
        g = info.get(group_key)
        # '-' は JP の CSV に出る未分類マーカー（production と同じ扱い）
        if g and pd.notna(g) and g not in ('N/A', '-'):
            group_symbols[g].append(sym)

    # 🔴 production（scripts/daily/3_calculate_rs.py の calculate_group_rs_weighted、
    #    scripts/jp/2_calculate_jp_rs.py の calc_group_percentile）と**同じ行列演算**で
    #    書く。日付×銘柄の二重ループでも結果は同じだが、式が違うと定義が
    #    いつの間にか乖離する。速度もこちらが速い。
    rs_df = pd.DataFrame({s: {d: v[0] for d, v in rows.items()}
                          for s, rows in per_symbol.items()})
    rs_df = rs_df.sort_index()

    if weight_mode == 'pointintime':
        # その日の close×volume。将来情報を使わない。
        # close/volume が欠ける日は NaN のままにして、その銘柄をその日だけ
        # 分子・分母とも除外する（重み1で混ぜると売買代金加重の中に
        # 等加重が紛れ、定義が濁る）
        w_df = pd.DataFrame({
            s: {d: (v[1] * v[2]) if (v[1] is not None and v[2] is not None) else None
                for d, v in rows.items()}
            for s, rows in per_symbol.items()})
        w_df = w_df.reindex(index=rs_df.index, columns=rs_df.columns)
    elif weight_mode == 'equal':
        w_df = pd.DataFrame(1.0, index=rs_df.index, columns=rs_df.columns)
    else:                                   # latest（旧 production 互換）
        w_df = pd.DataFrame(
            {s: float(weights.get(s, 1)) for s in rs_df.columns},
            index=rs_df.index)

    def aggregate(members, rows):
        """{group: [sym]} と対象日で、生値と有効銘柄数を返す。"""
        raw, eff = {}, {}
        for g, syms in members.items():
            syms = [c for c in syms if c in rs_df.columns]
            if not syms:
                continue
            sub = rs_df.loc[rows, syms]
            wg = w_df.loc[rows, syms]
            valid = sub.notna() & wg.notna()
            numer = (sub * wg).where(valid).sum(axis=1)
            denom = wg.where(valid).sum(axis=1)
            # 🔴 該当銘柄0件の群は NaN = その日の順位付けに参加しない
            raw[g] = numer / denom.replace(0, np.nan)
            eff[g] = valid.sum(axis=1)
        return raw, eff

    if pit is None:
        group_raw, eff_counts = aggregate(group_symbols, rs_df.index)
        stock_count_by_date = None
    else:
        # 🔴 スナップショットごとに構成銘柄が変わる。区間に切って集計し、
        #    縦に積む。percentile は日ごとに計算するので、区間で群の集合が
        #    違っても（外部結合で NaN になり）その日の順位付けから外れるだけ。
        parts_raw, parts_eff = [], []
        stock_count_by_date = {}
        for snap, days in segments_for(rs_df.index, pit.keys()).items():
            table = pit[snap]
            members = defaultdict(list)
            for sym in rs_df.columns:
                info = table.get(str(sym)[:4])
                if not info:
                    continue
                g = info.get(group_key)
                if g and g not in PIT_EXCLUDE:
                    members[g].append(sym)
            raw, eff = aggregate(members, days)
            if not raw:
                continue
            parts_raw.append(pd.DataFrame(raw))
            parts_eff.append(pd.DataFrame(eff))
            cnt = {g: len(v) for g, v in members.items()}
            for d in days:
                stock_count_by_date[d] = cnt
        if not parts_raw:
            return [], {}
        group_raw = pd.concat(parts_raw).sort_index()
        eff_counts = pd.concat(parts_eff).sort_index()

    if group_raw is None or (hasattr(group_raw, '__len__') and len(group_raw) == 0):
        return [], {}

    df = group_raw if isinstance(group_raw, pd.DataFrame) else pd.DataFrame(group_raw)
    effective = (eff_counts if isinstance(eff_counts, pd.DataFrame)
                 else pd.DataFrame(eff_counts)).reindex(df.index)
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    effective.index = df.index
    df = df.sort_index()
    effective = effective.sort_index()
    pct = df.rank(axis=1, pct=True) * 98 + 1

    # stock_count は production と同じく symbols_info からの固定値
    stock_count = defaultdict(int)
    for info in symbols_info.values():
        g = info.get(group_key)
        if g and pd.notna(g) and g not in ('N/A', '-'):
            stock_count[g] += 1

    industry_to_sector = {}
    if group_key == 'industry':
        # pit のときは分類も時点対応させる（新しい順に見て最後に勝った対応を残す）
        srcs = ([t.values() for t in pit.values()] if pit
                else [symbols_info.values()])
        for src in srcs:
            for info in src:
                ind = info.get('industry')
                if ind and ind not in PIT_EXCLUDE:
                    industry_to_sector.setdefault(ind, info.get('sector', 'N/A'))

    records = []
    per_date_groups = []
    for ts in pct.index:
        row = pct.loc[ts].dropna()
        if row.empty:
            continue
        per_date_groups.append(len(row))
        date_str = ts.strftime('%Y-%m-%d')
        for g, v in row.items():
            rec = {
                'date': date_str,
                group_key: g,
                'rs_percentile': round(float(v), 2),
                'rank': int((row > v).sum() + 1),
                # pit のときは、その日に適用されたスナップショットでの本数
                'stock_count': ((stock_count_by_date.get(date_str, {}).get(g, 0))
                                if stock_count_by_date is not None
                                else stock_count.get(g, 0)),
            }
            if group_key == 'industry':
                rec['sector'] = industry_to_sector.get(g, 'N/A')
            records.append(rec)

    # 🔴 並び順を (date, group) で決定的にする。
    #    順序が実装依存だと、値が同一でもファイルが一致せず、
    #    「再生成して前回と同じか」を機械的に確認できない。
    records.sort(key=lambda r: (r['date'], r[group_key]))

    # 診断: 有効銘柄数の分布（初期年で「1銘柄だけの群」がどれだけ出るか）
    # 0 は「その群にその日1銘柄も無い」= 順位付けに参加していないので数えない
    ncounts = effective.to_numpy().ravel()
    ncounts = ncounts[ncounts > 0]
    diag = {
        'dates': len(per_date_groups),
        'groups_min': min(per_date_groups) if per_date_groups else 0,
        'groups_max': max(per_date_groups) if per_date_groups else 0,
        'groups_median': int(np.median(per_date_groups)) if per_date_groups else 0,
        'n1_share': (float((ncounts == 1).mean()) if len(ncounts) else 0.0),
        'n_lt5_share': (float((ncounts < 5).mean()) if len(ncounts) else 0.0),
    }
    return records, diag


def write_local(records, group_key, year):
    """🔴 一時ファイルに書いてから rename する（原子的置換）。

    直接 open(p,'w') で書くと、同じ年を2プロセスが同時に書いたときに
    内容が混ざる。実際に踏んだ: 生き残っていたバックグラウンドジョブと
    区間実行が industry/2020.json を同時に書き、4MB 境界で壊れた
    （JSON として壊れていたので監査で検出できたが、運が悪ければ
    「パースは通るが中身が混ざったファイル」になり得た）。
    """
    d = os.path.join(OUT_ROOT, group_key)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{year}.json')
    tmp = f'{p}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        json.dump(records, f)
    os.replace(tmp, p)
    return p


def compare_r2(bucket, group_key, year, records):
    """既存 R2 と rs_percentile / rank を突き合わせる（等価性の検証用）。"""
    s3 = create_s3_client()
    try:
        old = json.loads(s3.get_object(
            Bucket=bucket, Key=f'{SCORES_PREFIX}/{group_key}/{year}.json'
        )['Body'].read())
    except Exception as e:
        logging.warning(f'  R2 に {group_key}/{year}.json なし: {e}')
        return
    key = lambda r: (r['date'], r[group_key])
    a = {key(r): r for r in old}
    b = {key(r): r for r in records}
    only_old = len(set(a) - set(b))
    only_new = len(set(b) - set(a))
    common = sorted(set(a) & set(b))
    dp = sum(1 for k in common if abs(a[k]['rs_percentile'] - b[k]['rs_percentile']) > 1e-9)
    dr = sum(1 for k in common if a[k]['rank'] != b[k]['rank'])
    ds = sum(1 for k in common if a[k].get('stock_count') != b[k].get('stock_count'))
    logging.info(f'  [R2比較] {group_key}/{year}: 旧{len(a):,} 新{len(b):,} '
                 f'旧のみ{only_old} 新のみ{only_new} / 共通{len(common):,} 中 '
                 f'percentile差{dp} rank差{dr} stock_count差{ds}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', choices=['us', 'jp'], default='us')
    ap.add_argument('--classification', choices=['current', 'pit'], default='current',
                    help='current: 現在のユニバースCSVの分類を全歴史に当てる（既定）/ '
                         'pit: その日以前の直近スナップショットの分類を使う。'
                         'JP のみ（J-Quants 月次マスタ 2008-05〜）。'
                         'US には同等の履歴が無い')
    ap.add_argument('--years', required=True, help='例 1988-2026 / 2024 / 2024,2025')
    ap.add_argument('--build', action='store_true', help='ローカル生成のみ')
    ap.add_argument('--execute', action='store_true', help='生成後 R2 へ一括投入')
    ap.add_argument('--compare-r2', action='store_true', help='既存R2と突き合わせる')
    ap.add_argument('--resume', action='store_true',
                    help='ローカルに生成済みの年はスキップ（中断からの再開用）')
    ap.add_argument('--weight-mode',
                    choices=['pointintime', 'latest', 'equal'],
                    default='pointintime',
                    help='pointintime: その日の close×volume（look-ahead なし・既定）/ '
                         'latest: 最新日の close×volume（旧 production と同一・'
                         '歴史日付に将来の売買代金を当てる）/ '
                         'equal: 等加重')
    args = ap.parse_args()

    global M, TARGET_STOCKS_CSV, OUT_ROOT, CORE_PREFIX, SCORES_PREFIX
    M = MARKETS[args.market]
    TARGET_STOCKS_CSV = M['csv']
    # 置き場は (分類, 重み) の組み合わせごとに分ける。
    # 🔴 等加重は**別系統**として保存する（同じレコードに2つの値を入れない）。
    #    等加重では出来高0の群が落ちないため、売買代金加重とは
    #    (date, group) の行集合そのものが違う。1レコードに混ぜると
    #    どちらかに null が入り、「値が無い」と「その加重では群が成立しない」
    #    の区別が消える。研究側は (date, group) で結合する。
    suffix = '_ew' if args.weight_mode == 'equal' else ''
    OUT_ROOT = M['out'] + ('_pit' if args.classification == 'pit' else '') + suffix
    CORE_PREFIX = M['core']
    SCORES_PREFIX = M['scores'] + suffix

    years = parse_years(args.years)
    bucket = os.environ.get('R2_BUCKET_NAME', 'stock-data')

    logging.info('=' * 60)
    logging.info(f'[{args.market}] RS_scores 全期間再生成  {years[0]}..{years[-1]} ({len(years)}年)  '
                 f'weight={args.weight_mode} class={args.classification}  '
                 f'{"EXECUTE" if args.execute else "BUILD/COMPARE"}')
    logging.info('=' * 60)

    # 🔴 --resume はファイルの有無しか見ない。別の --weight-mode で作った年が
    #    混ざると、1つのヴィンテージの中に2つの定義が同居する（今回の障害そのもの）。
    #    実際に latest で検証した 2024 が残っていて危うく混入するところだった。
    #    モードを記録し、食い違ったら止める。
    os.makedirs(OUT_ROOT, exist_ok=True)
    marker = os.path.join(OUT_ROOT, '_vintage.json')
    if os.path.exists(marker):
        with open(marker, encoding='utf-8') as f:
            prev = json.load(f)
        if (prev.get('weight_mode') != args.weight_mode
                or prev.get('classification', 'current') != args.classification):
            logging.error(
                f'既存の生成物は weight_mode={prev.get("weight_mode")} / '
                f'classification={prev.get("classification", "current")} です。'
                f'今回は {args.weight_mode} / {args.classification}。混ぜられません。'
                f'{OUT_ROOT} を消してから作り直してください')
            return False
    else:
        with open(marker, 'w', encoding='utf-8') as f:
            json.dump({'weight_mode': args.weight_mode,
                       'classification': args.classification}, f)

    symbols_info = download_universe(bucket)
    # 🔴 ユニバースCSVに ticker が NaN(float) の行が混ざっている。
    # そのままだとソートで落ちるうえ、core のキーにもならないので除外する。
    bad = [k for k in symbols_info if not isinstance(k, str) or not k.strip()]
    if bad:
        logging.warning(f'ticker が不正な行を {len(bad)} 件除外: {bad[:5]}')
        for k in bad:
            symbols_info.pop(k)
    symbols = sorted(symbols_info)
    logging.info(f'ユニバース {len(symbols):,} 銘柄')

    pit = None
    if args.classification == 'pit':
        if args.market != 'jp':
            logging.error('--classification pit は JP のみ。'
                          'US には過去の分類履歴が存在しない')
            return False
        pit = load_pit_classification(bucket)

    weights = {}
    if args.weight_mode == 'latest':
        logging.info('重み（最新日 close×volume）を読み込み中...')
        weights = load_weights(symbols, bucket)
        logging.info(f'  重み確定 {len(weights):,} 銘柄')

    produced = defaultdict(dict)     # group_key -> {year: path}
    for year in years:
        # 39年ぶんは1時間規模になる。中断しても捨てないよう、生成済みの年は飛ばす。
        # （--execute は最後にまとめて上げるので、再開しても原子性は崩れない）
        done_paths = {gk: os.path.join(OUT_ROOT, gk, f'{year}.json')
                      for gk in ('sector', 'industry')}
        if args.resume and all(os.path.exists(p) for p in done_paths.values()):
            logging.info(f'--- {year} 生成済み。スキップ ---')
            for gk, p in done_paths.items():
                produced[gk][year] = p
            continue

        logging.info(f'--- {year} ---')
        per_symbol = load_year(symbols, bucket, year)
        if not per_symbol:
            logging.warning(f'  {year}: core にデータなし。スキップ')
            continue
        logging.info(f'  {year}: {len(per_symbol):,} 銘柄に rs_percentile あり')
        for gk in ('sector', 'industry'):
            records, diag = build_year(per_symbol, weights, symbols_info, gk,
                                       args.weight_mode, pit=pit)
            if not records:
                logging.warning(f'  {year} {gk}: レコード0。スキップ')
                continue
            logging.info(
                f'  {gk}: {len(records):,}件 / {diag["dates"]}日 / '
                f'有効群数 中央{diag["groups_median"]} '
                f'({diag["groups_min"]}..{diag["groups_max"]}) / '
                f'銘柄1件の群 {diag["n1_share"]*100:.1f}% / '
                f'5件未満 {diag["n_lt5_share"]*100:.1f}%')
            produced[gk][year] = write_local(records, gk, year)
            if args.compare_r2:
                compare_r2(bucket, gk, year, records)

    if not args.execute:
        logging.info('生成のみで終了（R2 へは書いていない）')
        return True

    # 🔴 全年を作り終えてからまとめて上げる（新旧混在の期間を作らない）
    total = sum(len(v) for v in produced.values())
    logging.info(f'R2 へ一括投入: {total} ファイル')

    # 🔴 グループの構成銘柄は metadata/target_stocks_latest.csv に依存する。
    #    これは毎月1日の cron で上書きされ（市場ETF追加などで手動注入も入る）、
    #    日付版が残っていない。スナップショットを残さないとこのヴィンテージは
    #    二度と再現できない。スコア本体より先に上げる。
    stamp = datetime.now().strftime('%Y-%m-%d')
    snap_key = M['snapshot'].format(stamp=stamp)
    try:
        s3 = create_s3_client()
        s3.upload_file(TARGET_STOCKS_CSV, bucket, snap_key)
        logging.info(f'  ユニバース保存: {snap_key}')
    except Exception as e:
        logging.error(f'  ✗ ユニバース保存に失敗: {e}')
        logging.error('  スナップショット無しでは再現できないため中止する')
        return False

    manifest = {
        'generated': stamp,
        'weight_mode': args.weight_mode,
        'classification': args.classification,
        'universe_snapshot': snap_key,
        'years': [min(y for v in produced.values() for y in v),
                  max(y for v in produced.values() for y in v)],
        'definition': (
            'group_raw = Σ(individual rs_percentile × その日の close×volume) / Σ(その日の close×volume); '
            'close/volume が欠ける銘柄はその日除外; 該当銘柄0件の群は順位付けに不参加; '
            'rs_percentile = rank(axis=1, pct=True) × 98 + 1; rs_raw は出力しない; '
            f'分類は {"その日以前の直近スナップショット(時点対応)" if args.classification == "pit" else "現在のユニバースCSV(全歴史に適用)"}'),
        'note': ('2026-08-17 の全期間再生成。これ以前の scores/RS_scores は '
                 '2024-01-02 を境に定義が2つ連結されており、重みも最新日の '
                 'close×volume（look-ahead かつ毎日履歴が変わる）だった'),
    }

    ok = fail = 0
    for gk, by_year in produced.items():
        for year, path in sorted(by_year.items()):
            try:
                s3 = create_s3_client()      # 都度生成（再利用しない）
                s3.upload_file(path, bucket, f'{SCORES_PREFIX}/{gk}/{year}.json')
                ok += 1
            except Exception as e:
                logging.error(f'  ✗ {gk}/{year}: {e}')
                fail += 1
    if fail == 0:
        # 🔴 マニフェストは**スコア本体が全部上がってから**書く。
        #    先に書くと、途中で失敗したときに「完了した版」の目印だけが残る。
        try:
            s3 = create_s3_client()
            s3.put_object(Bucket=bucket,
                          Key=f'{SCORES_PREFIX}/_vintage.json',
                          Body=json.dumps(manifest, ensure_ascii=False,
                                          indent=1).encode('utf-8'))
            logging.info(f'  マニフェスト: {SCORES_PREFIX}/_vintage.json')
        except Exception as e:
            logging.error(f'  ✗ マニフェスト書込に失敗: {e}')
            fail += 1

    logging.info(f'✅ 成功{ok} / 失敗{fail}')
    return fail == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
