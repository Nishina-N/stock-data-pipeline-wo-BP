"""2_fetch_delisted_bars.py

上場廃止銘柄の日次4本値を、銘柄ごとに全履歴で取得する。

これが Premium 契約の必須理由①。当方のパネルは「いま上場している銘柄」だけで
できているため、消えた銘柄が構造的に欠落している。接ぎ木試験（研究側）では
この欠落が凍結値を大きく持ち上げていることが分かっている。

前提: 1_fetch_calendar_master.py が data/jquants/delisted_codes.json を出していること。

出力: data/jquants/delisted_bars/{code}.json   （1銘柄1ファイル・再開可能）

使い方:
  python scripts/jp/jquants/2_fetch_delisted_bars.py --limit 5   # ドライラン
  python scripts/jp/jquants/2_fetch_delisted_bars.py             # 全件
"""
import os
import sys
import json
import time
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jq_client import Client, JQuantsError
from _jq_rates import interval_for, check_budget

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DATA_ROOT = os.path.join('data', 'jquants')
DELISTED_JSON = os.path.join(DATA_ROOT, 'delisted_codes.json')
OUT_DIR = os.path.join(DATA_ROOT, 'delisted_bars')

BARS_INTERVAL = interval_for('delisted_bars')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None, help='先頭N銘柄（ドライラン用）')
    args = ap.parse_args()

    if not os.path.exists(DELISTED_JSON):
        logging.error(f'{DELISTED_JSON} がありません。'
                      '先に 1_fetch_calendar_master.py を実行してください')
        return False

    with open(DELISTED_JSON, encoding='utf-8') as f:
        meta = json.load(f)
    codes = [c['Code'] for c in meta['codes']]
    if args.limit:
        codes = codes[:args.limit]
        logging.info(f'DRY-RUN: 先頭 {len(codes)} 銘柄のみ')

    logging.info('=' * 60)
    logging.info(f'廃止銘柄の日次4本値: {len(codes):,} 銘柄  '
                 f'レート {60 / BARS_INTERVAL:.0f}/分 → 最短 {len(codes) * BARS_INTERVAL / 60:.0f} 分'
                 f'（設定合計 {check_budget()}/分・同時実行は Premium 500/分以内に収める）')
    logging.info('=' * 60)

    os.makedirs(OUT_DIR, exist_ok=True)
    client = Client(min_interval=BARS_INTERVAL)
    got = skipped = empty = 0
    t0 = time.monotonic()

    for i, code in enumerate(codes, 1):
        out = os.path.join(OUT_DIR, f'{code}.json')
        if os.path.exists(out):
            skipped += 1
            continue
        try:
            rows = client.get('/equities/bars/daily', {'code': code})
        except JQuantsError as e:
            logging.error(f'  {code}: {e}')
            logging.error('再実行すれば取得済みはスキップして続きから再開します')
            return False

        # 空でも書く（未取得と区別するため。上場期間が下限より前の銘柄は 0 件になる）
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        got += 1
        if not rows:
            empty += 1

        if got % 50 == 0 or i == len(codes):
            el = time.monotonic() - t0
            eta = (len(codes) - i) / (got / el) / 60 if got and el else 0
            logging.info(f'  {i}/{len(codes)}  {code}  {len(rows):,}行  '
                         f'取得{got} skip{skipped} 空{empty}  残り約{eta:.0f}分')

    logging.info(f'✅ 取得{got} / キャッシュ{skipped} / 空{empty}')
    logging.info(f'API呼び出し {client.n_calls:,} 回 / 429 {client.n_429} 回')
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
