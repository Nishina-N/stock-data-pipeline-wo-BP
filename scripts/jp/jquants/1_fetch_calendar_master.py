"""1_fetch_calendar_master.py

取引カレンダーと、上場銘柄一覧（master）の月次スナップショットを取得する。
これが「いつ銘柄が消えたか」＝サバイバーシップ補正の土台になる。

🔴 master?date= の罠（2026-08-15 実測）:
   データ下限 2008-05-07 より前の日付を指定すると **エラーではなく 200 が返り、
   中身は 2008-05-07 のスナップショット**（Code集合が完全一致・差分0）。
   そのまま貯めると「2006年に上場していた」という存在しない記録を捏造する。
   レコードの `Date` 列が要求日と一致するかで検出できるため、不一致は破棄する。

出力（ローカルのチェックポイント。R2 投入は 5_upload_jquants_r2.py）:
  data/jquants/calendar.json          取引カレンダー全期間
  data/jquants/master/{YYYY-MM}.json  月末営業日時点の上場銘柄一覧
  data/jquants/delisted_codes.json    master から導出した「消えた銘柄」一覧

使い方:
  python scripts/jp/jquants/1_fetch_calendar_master.py            # 全期間・再開可
  python scripts/jp/jquants/1_fetch_calendar_master.py --limit 3  # ドライラン
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jq_client import Client, PRICE_START, JQuantsError
from _jq_rates import interval_for, check_budget

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

OUT_DIR = os.path.join('data', 'jquants')
MASTER_DIR = os.path.join(OUT_DIR, 'master')
CALENDAR_JSON = os.path.join(OUT_DIR, 'calendar.json')
DELISTED_JSON = os.path.join(OUT_DIR, 'delisted_codes.json')

MASTER_INTERVAL = interval_for('master')


def fetch_calendar(client):
    """取引カレンダーを取得。既にあれば再取得しない。"""
    if os.path.exists(CALENDAR_JSON):
        with open(CALENDAR_JSON, encoding='utf-8') as f:
            rows = json.load(f)
        logging.info(f'calendar: キャッシュ {len(rows):,} 件')
        return rows

    rows = client.get('/markets/calendar')
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CALENDAR_JSON, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False)
    logging.info(f'calendar: {len(rows):,} 件 取得')
    return rows


# 株式の立会がある区分だけ。実測（2026-08-15）:
#   '1' 営業日          … bars/daily に全銘柄あり
#   '2' 東証半日立会     … 2008-12-30 / 2009-01-05 とも 2,489 銘柄あり → 営業日
#   '3' 祝日取引日       … 2022-09-23 等いずれも bars/daily n=0（デリバティブのみ）→ 除外
#   '0' 非営業日
# '3' を営業日に含めると 67 日ぶんの空振り呼び出しが全系統で発生する
TRADING_HOLDIV = {'1', '2'}


def business_days(calendar_rows, start, end):
    """株式の立会がある日の昇順リスト。"""
    days = sorted({r['Date'] for r in calendar_rows
                   if str(r.get('HolDiv')) in TRADING_HOLDIV
                   and start <= r['Date'] <= end})
    return days


def month_end_days(days):
    """各月の最終営業日だけを残す。"""
    last = {}
    for d in days:
        last[d[:7]] = d          # 昇順なので後勝ちで月末になる
    return [last[m] for m in sorted(last)]


def fetch_master_snapshots(client, targets):
    """月末営業日ごとに master を取得。取得済みはスキップ（再開可能）。"""
    os.makedirs(MASTER_DIR, exist_ok=True)
    got, skipped, clamped = 0, 0, []

    for i, date in enumerate(targets, 1):
        path = os.path.join(MASTER_DIR, f'{date[:7]}.json')
        if os.path.exists(path):
            skipped += 1
            continue

        rows = client.get('/equities/master', {'date': date})

        # 🔴 下限より前は 2008-05-07 のスナップショットが返る。Date 列で検出して破棄
        actual = rows[0].get('Date') if rows else None
        if actual and actual != date:
            clamped.append((date, actual))
            logging.warning(f'  {date}: 要求日と異なる Date={actual} が返ったため破棄'
                            f'（契約下限より前のクランプ）')
            continue

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        got += 1
        if i % 20 == 0 or i == len(targets):
            logging.info(f'  master {i}/{len(targets)}  {date}  '
                         f'{len(rows):,}銘柄  (取得{got} skip{skipped})')

    logging.info(f'master: 新規{got} / キャッシュ{skipped} / クランプ破棄{len(clamped)}')
    return clamped


def derive_delisted():
    """月次スナップショットを突き合わせ、最新に居ない銘柄＝廃止銘柄を導出する。

    社名での突合でコード変更が0件だったことは A-3 の研究ログで確認済みなので、
    「最新スナップショットに居ない = 実質的な上場廃止」として扱う。
    """
    files = sorted(f for f in os.listdir(MASTER_DIR) if f.endswith('.json'))
    if not files:
        logging.error('master スナップショットがありません')
        return None

    first_seen, last_seen, info = {}, {}, {}
    for fn in files:
        month = fn[:-5]
        with open(os.path.join(MASTER_DIR, fn), encoding='utf-8') as f:
            rows = json.load(f)
        for r in rows:
            code = r['Code']
            first_seen.setdefault(code, month)
            last_seen[code] = month
            info[code] = r          # 最後に見えたときの属性を残す

    latest_month = files[-1][:-5]
    delisted = [
        {
            'Code': c,
            'CoName': info[c].get('CoName'),
            'first_seen': first_seen[c],
            'last_seen': last_seen[c],
            'S33': info[c].get('S33'),
            'S33Nm': info[c].get('S33Nm'),
            'S17': info[c].get('S17'),
            'MktNm': info[c].get('MktNm'),
        }
        for c in sorted(first_seen) if last_seen[c] != latest_month
    ]

    with open(DELISTED_JSON, 'w', encoding='utf-8') as f:
        json.dump({'generated': datetime.now().isoformat(),
                   'latest_month': latest_month,
                   'n_ever_listed': len(first_seen),
                   'n_delisted': len(delisted),
                   'codes': delisted}, f, ensure_ascii=False)

    logging.info(f'延べ上場 {len(first_seen):,} / 最新在籍 '
                 f'{len(first_seen) - len(delisted):,} / 廃止 {len(delisted):,}')
    return delisted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None,
                    help='先頭N月だけ取得（ドライラン用）')
    ap.add_argument('--start', default=PRICE_START,
                    help=f'開始日（既定={PRICE_START}＝実測のデータ下限）')
    args = ap.parse_args()

    client = Client(min_interval=MASTER_INTERVAL)
    logging.info('=' * 60)
    logging.info('J-QUANTS: calendar + master 月次スナップショット')
    logging.info(f'  レート {60 / MASTER_INTERVAL:.0f}/分 '
                 f'（設定合計 {check_budget()}/分・同時実行は Premium 500/分以内に収める）')
    logging.info('=' * 60)

    cal = fetch_calendar(client)
    today = datetime.now().strftime('%Y-%m-%d')
    days = business_days(cal, args.start, today)
    if not days:
        logging.error('営業日が0件。カレンダーの範囲を確認してください')
        return False
    logging.info(f'営業日 {len(days):,} 日  {days[0]}..{days[-1]}')

    targets = month_end_days(days)
    if args.limit:
        targets = targets[:args.limit]
        logging.info(f'DRY-RUN: 先頭 {len(targets)} 月のみ')
    logging.info(f'master 取得対象 {len(targets)} 月 '
                 f'（最短 {len(targets) * MASTER_INTERVAL / 60:.0f} 分）')

    try:
        fetch_master_snapshots(client, targets)
    except JQuantsError as e:
        logging.error(f'取得中断: {e}')
        logging.error('再実行すれば取得済みの月はスキップして続きから再開します')
        return False

    if not args.limit:
        derive_delisted()

    logging.info(f'API呼び出し {client.n_calls:,} 回 / 429 {client.n_429} 回')
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
