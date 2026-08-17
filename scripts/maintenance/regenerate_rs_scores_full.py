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
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, 'target_stocks_latest.csv')
OUT_ROOT = os.path.join(DATA_FOLDER, 'regen_rs_scores')
CORE_PREFIX = 'stocks/daily/core'
SCORES_PREFIX = 'scores/RS_scores'

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
    obj = s3.get_object(Bucket=bucket, Key='metadata/target_stocks_latest.csv')
    with open(TARGET_STOCKS_CSV, 'wb') as f:
        f.write(obj['Body'].read())
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


def build_year(per_symbol, weights, symbols_info, group_key, weight_mode):
    """1年ぶんのレコードを作る。戻り値: (records, 診断dict)"""
    group_symbols = defaultdict(list)
    for sym in per_symbol:
        info = symbols_info.get(sym)
        if not info:
            continue
        g = info.get(group_key)
        if g and pd.notna(g) and g != 'N/A':
            group_symbols[g].append(sym)

    all_dates = sorted({d for rows in per_symbol.values() for d in rows})

    group_raw = defaultdict(dict)
    effective = defaultdict(dict)      # group -> {date: 有効銘柄数}
    for g, syms in group_symbols.items():
        for date in all_dates:
            num = den = 0.0
            n = 0
            for sym in syms:
                rec = per_symbol[sym].get(date)
                if rec is None:
                    continue
                rs, close, volume = rec
                if weight_mode == 'equal':
                    w = 1
                elif weight_mode == 'pointintime':
                    # 🔴 その日の close×volume。将来情報を使わない。
                    # close/volume が欠けている日は重みを決められないので
                    # その銘柄をその日だけ除外する（重み1で混ぜると
                    # 売買代金加重の中に等加重が紛れ、定義が濁る）
                    if close is None or volume is None:
                        continue
                    w = close * volume
                else:
                    w = weights.get(sym, 1)
                num += rs * w
                den += w
                n += 1
            # 🔴 該当銘柄0件の群は値を持たない = その日の順位付けに参加しない
            if den > 0:
                group_raw[g][date] = num / den
                effective[g][date] = n

    if not group_raw:
        return [], {}

    df = pd.DataFrame(group_raw).reindex(all_dates)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    pct = df.rank(axis=1, pct=True) * 98 + 1

    # stock_count は production と同じく symbols_info からの固定値
    stock_count = defaultdict(int)
    for info in symbols_info.values():
        g = info.get(group_key)
        if g and pd.notna(g) and g != 'N/A':
            stock_count[g] += 1

    industry_to_sector = {}
    if group_key == 'industry':
        for info in symbols_info.values():
            ind = info.get('industry')
            if ind and ind not in industry_to_sector:
                industry_to_sector[ind] = info.get('sector', 'N/A')

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
                'stock_count': stock_count.get(g, 0),
            }
            if group_key == 'industry':
                rec['sector'] = industry_to_sector.get(g, 'N/A')
            records.append(rec)

    # 診断: 有効銘柄数の分布（初期年で「1銘柄だけの群」がどれだけ出るか）
    ncounts = [n for d in effective.values() for n in d.values()]
    diag = {
        'dates': len(per_date_groups),
        'groups_min': min(per_date_groups) if per_date_groups else 0,
        'groups_max': max(per_date_groups) if per_date_groups else 0,
        'groups_median': int(np.median(per_date_groups)) if per_date_groups else 0,
        'n1_share': (sum(1 for n in ncounts if n == 1) / len(ncounts)
                     if ncounts else 0.0),
        'n_lt5_share': (sum(1 for n in ncounts if n < 5) / len(ncounts)
                        if ncounts else 0.0),
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

    years = parse_years(args.years)
    bucket = os.environ.get('R2_BUCKET_NAME', 'stock-data')

    logging.info('=' * 60)
    logging.info(f'RS_scores 全期間再生成  {years[0]}..{years[-1]} ({len(years)}年)  '
                 f'weight={args.weight_mode}  '
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
        if prev.get('weight_mode') != args.weight_mode:
            logging.error(
                f'既存の生成物は weight_mode={prev.get("weight_mode")} です。'
                f'今回は {args.weight_mode}。混ぜられません。'
                f'{OUT_ROOT} を消してから作り直してください')
            return False
    else:
        with open(marker, 'w', encoding='utf-8') as f:
            json.dump({'weight_mode': args.weight_mode}, f)

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
                                       args.weight_mode)
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
    logging.info(f'✅ 成功{ok} / 失敗{fail}')
    return fail == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
