"""6_fetch_bulk.py

`/bulk/list` + `/bulk/get` で月次 gzip CSV を一括取得する。

日次 API を営業日ぶん叩く（4,471回）代わりに月次ファイル（〜228本）で済むため、
大容量系統では桁違いに速い。225オプションは API 経由だと約4時間かかるが
bulk なら 255MB のダウンロードで終わる。

🔴 bulk を信用しすぎないこと（FMP で最新データ欠落の実績あり）。
   `--verify` を付けると、取得後に同じ日を日次 API でも引いて件数を突き合わせる。
   実行時は必ず1回は検証すること。

⚠️ EDINET 系は bulk 非対応（"This endpoint is not available for csv download"）。
   3_fetch_bydate_series.py の日次 API で取る。

出力: data/jquants/_bulk/{dataset}/{ファイル名}.csv.gz （取得済みはスキップ）

使い方:
  python scripts/jp/jquants/6_fetch_bulk.py --dataset indices
  python scripts/jp/jquants/6_fetch_bulk.py --dataset options225 --verify
  python scripts/jp/jquants/6_fetch_bulk.py --all
"""
import os
import sys
import gzip
import argparse
import logging

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jq_client import Client, JQuantsError

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DATA_ROOT = os.path.join('data', 'jquants')
BULK_ROOT = os.path.join(DATA_ROOT, '_bulk')

# dataset -> API エンドポイント（bulk/list の endpoint パラメータに渡す値）
BULK_DATASETS = {
    'options225':        '/derivatives/bars/daily/options/225',
    'futures':           '/derivatives/bars/daily/futures',
    'indices':           '/indices/bars/daily',
    'short_sale_report': '/markets/short-sale-report',
    'earnings_date':     '/fins/earnings-date',
    # 🔴 /equities/bars/daily は bulk を使わないこと。
    #    bulk は Adj*（AdjO/AdjC/MAdj*/AAdj* の15列）を落としており、
    #    API 44列に対し 29列しか無い（行数は一致するので件数比較では気づけない）。
    #    delisted_bars は API 経由で44列あるため、bulk で取ると
    #    同じ名前空間に列構成の違う4本値が並ぶ。3_fetch_bydate_series.py で取る。
    #
    # /indices/bars/daily/topix も不要。indices の Code='0000' と同一
    #    （2016-09 の終値 20/20 一致を確認済み）。
}

# 検証時に日次 API へ渡す日付パラメータ名。既定は 'date' だが、
# /markets/short-sale-report は 'date' を受け付けず 400 を返す
# （"requires at least 1 parameter as follows; 'code','disc_date','calc_date'"）
VERIFY_DATE_PARAM = {
    'short_sale_report': 'disc_date',
}

# 🔴 date パラメータが効かず、指定しても**全期間**を返す系統。
# 件数の単純比較だと必ず不一致になる（topix は bulk 1行 vs API 4,471行）ので、
# API 側を日付で絞ってから比較する。
IGNORES_DATE_PARAM = {'topix'}


def list_files(client, endpoint):
    return client.get('/bulk/list', {'endpoint': endpoint})


def download(client, key, out_path):
    """署名付き URL を取得して落とす。URL 自体は認証不要なので素の requests で取る。"""
    body = client._get_once('/bulk/get', {'key': key})
    url = body.get('url')
    if not url:
        raise JQuantsError(f'bulk/get が url を返しませんでした: {key}')

    r = requests.get(url, timeout=300)
    r.raise_for_status()
    # gzip として妥当か確認してから保存（壊れたファイルをキャッシュしない）
    gzip.decompress(r.content)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(r.content)
    return len(r.content)


def verify(client, dataset, endpoint):
    """bulk で落とした内容を日次 API と突き合わせる。

    bulk の欠落は静かに効くので、件数が一致することを1日ぶん確認する。
    """
    import glob
    import csv
    import collections

    files = sorted(glob.glob(os.path.join(BULK_ROOT, dataset, '**', '*.csv.gz'),
                             recursive=True))
    if not files:
        logging.warning('検証対象がありません')
        return True

    # 真ん中あたりのファイルを使う（先頭/末尾は境界で特殊なことがある）
    target = files[len(files) // 2]
    with gzip.open(target, 'rt', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        logging.warning(f'{target} が空です')
        return True

    date_col = 'Date' if 'Date' in rows[0] else next(
        (c for c in rows[0] if 'Date' in c), None)
    if date_col is None:
        logging.warning(f'日付列が見つからないため検証を省略: {list(rows[0])}')
        return True

    counts = collections.Counter(r[date_col] for r in rows)
    day, n_bulk = counts.most_common(1)[0]

    param = VERIFY_DATE_PARAM.get(dataset, 'date')
    try:
        api_rows = client.get(endpoint, {param: day})
    except JQuantsError as e:
        # 検証できないこと自体はデータの不備ではない（ダウンロード時に
        # gzip として妥当かは確認済み）。取得全体を失敗させない
        logging.warning(f'  検証を実施できませんでした（{param}）: {e}')
        return True
    if dataset in IGNORES_DATE_PARAM:
        # 全期間が返るので、こちらで当該日に絞ってから数える
        api_rows = [r for r in api_rows if r.get(date_col) == day]
    n_api = len(api_rows)
    ok = n_bulk == n_api
    mark = '✓' if ok else '✗'
    logging.info(f'  {mark} 検証 {day}: bulk {n_bulk:,}行 / API {n_api:,}行'
                 f'{"" if ok else "  ← 不一致"}')

    # 🔴 行数だけでは足りない。/equities/bars/daily は bulk が Adj* 15列を
    #    落としている（API 44列 / bulk 29列）のに行数は一致する。
    #    列の欠落は静かに効くので必ず突き合わせる
    if api_rows:
        missing = sorted(set(api_rows[0]) - set(rows[0]))
        if missing:
            ok = False
            logging.error(f'  ✗ 列の欠落 {len(missing)}件: bulk に無い列 {missing}')
            logging.error('    → この系統は bulk ではなく日次 API で取得すること')
        else:
            logging.info(f'  ✓ 列一致 {len(api_rows[0])}列')
    return ok


def fetch(client, dataset, do_verify):
    endpoint = BULK_DATASETS[dataset]
    files = list_files(client, endpoint)
    total_mb = sum(f['Size'] for f in files) / 1e6
    logging.info(f'{dataset}: {len(files)} ファイル / {total_mb:.1f} MB')

    got = skipped = 0
    for i, f in enumerate(files, 1):
        key = f['Key']
        out = os.path.join(BULK_ROOT, dataset, os.path.basename(key))
        if os.path.exists(out):
            skipped += 1
            continue
        download(client, key, out)
        got += 1
        if got % 25 == 0 or i == len(files):
            logging.info(f'  {i}/{len(files)}  取得{got} skip{skipped}')

    logging.info(f'✅ {dataset}: 取得{got} / キャッシュ{skipped}')
    if do_verify:
        return verify(client, dataset, endpoint)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', choices=sorted(BULK_DATASETS))
    ap.add_argument('--all', action='store_true', help='全 bulk 対象を取得')
    ap.add_argument('--verify', action='store_true',
                    help='取得後に日次 API と件数を突き合わせる')
    args = ap.parse_args()

    if not args.dataset and not args.all:
        ap.error('--dataset か --all を指定してください')

    targets = sorted(BULK_DATASETS) if args.all else [args.dataset]
    client = Client(min_interval=0.5)

    ok = True
    for ds in targets:
        try:
            ok &= fetch(client, ds, args.verify)
        except (JQuantsError, requests.RequestException) as e:
            logging.error(f'{ds}: {e}')
            logging.error('再実行すれば取得済みはスキップして続きから再開します')
            return False

    logging.info(f'API呼び出し {client.n_calls:,} 回 / 429 {client.n_429} 回')
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
