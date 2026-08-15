"""3_fetch_bydate_series.py

日付単位で引く系統をまとめて取得する。

  fins_summary … /fins/summary   財務情報。**DiscDate / DiscTime = 決算の実発表日時**。
                 Premium の必須理由②。現行パネルの earningsDate は 2008-2013 で
                 充足率 17-39% しかなく残りは「会計期末+45日」の近似で、
                 その代償が実測で GEO -281pp（研究側ログ）。
  breakdown    … /markets/breakdown  売買内訳。現物売買 / 信用新規 / 信用返済 が
                 銘柄別・日次で分解される（A-2）。
  short_ratio  … /markets/short-ratio 空売り比率。**価格規制あり/なし の区分**。

🔴 台帳 A-2 の訂正（2026-08-15 実測）:
   「breakdown で信用新規売りが価格規制あり/なしに分かれる＝51単元(5,100株)規制を
   実測できる」は**誤り**。breakdown の16列に規制の区分は無い:
     LongSellVa/LongBuyVa(現物) ShrtNoMrgnVa(現物空売り)
     MrgnSellNewVa/MrgnBuyNewVa(信用新規) MrgnSellCloseVa/MrgnBuyCloseVa(信用返済)
   価格規制の区分は short-ratio 側の ShrtWithResVa / ShrtNoResVa にしか無く、
   しかも **33業種単位で銘柄別ではない**。MAXLOT 50 近似の検証は業種粒度が上限。

実測の開始年（2026-08-15）:
  fins_summary 2008-08〜 / breakdown 2015-04-01〜 / short_ratio 2010〜
台帳は breakdown を「20年」としているが**実際は11.4年**で、in-sample 前半には掛からない。

出力: data/jquants/{dataset}/{YYYY}/{YYYY-MM-DD}.json （1営業日1ファイル・再開可能）

使い方:
  python scripts/jp/jquants/3_fetch_bydate_series.py --dataset fins_summary
  python scripts/jp/jquants/3_fetch_bydate_series.py --dataset breakdown
  python scripts/jp/jquants/3_fetch_bydate_series.py --dataset fins_summary --limit 5
"""
import os
import sys
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jq_client import Client, JQuantsError
from _jq_bydate import fetch_by_date, fetch_range, load_business_days
from _jq_rates import interval_for, check_budget

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# dataset -> (APIパス, 日付パラメータ名, 実測の開始日, モード)
# モード: 'date'   … 全営業日を1日ずつ
#         'friday' … 金曜の営業日のみ（週次公表もの。他の曜日は 200 で 0 件）
#         'range'  … from/to で一括（日付パラメータが効かないもの）
# 呼び出し間隔は _jq_rates.py が一元管理する（プラン上限500/分の配分）
DATASETS = {
    'fins_summary':    ('/fins/summary',        'date', '2008-07-01', 'date'),
    # 2015-01〜03 は 200 で 0 件が返る。実データは 2015-04-01 から
    'breakdown':       ('/markets/breakdown',   'date', '2015-04-01', 'date'),
    # 空売り比率。**価格規制あり/なし の区分はここにしか無い**（breakdown には無い）。
    # ただし 33業種単位で銘柄別ではないため、51単元(5,100株)規制の検証は
    # 業種粒度が上限になる。1日34行（33業種＋計）と極小
    'short_ratio':     ('/markets/short-ratio', 'date', '2010-01-01', 'date'),
    # 財務諸表詳細(BS/PL/CF)。FS が125要素の入れ子辞書で1レコード約6.5KB。
    # /fins/summary と同じくプラン非依存で 60 req/分の個別上限
    'fins_details':    ('/fins/details',        'date', '2009-01-01', 'date'),
    # 配当金情報。2012 以前は 0 件（決算集中日で実測）
    'dividend':        ('/fins/dividend',       'date', '2013-01-01', 'date'),
    # 信用取引週末残高。**金曜しかデータが無い**（2025-06-23〜26 は全て 0、27(金) で 4,264）。
    # 全営業日を叩くと8割が空振りになるため friday モード
    'margin_interest': ('/markets/margin-interest', 'date', '2010-01-01', 'friday'),
    # 日々公表信用取引残高。日次
    'margin_alert':    ('/markets/margin-alert', 'date', '2008-05-07', 'date'),
    # 投資部門別。**date パラメータが効かず**（指定しても全期間が返る）、
    # from/to でしか絞れないため range モード
    'investor_types':  ('/equities/investor-types', None, '2008-01-01', 'range'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', required=True, choices=sorted(DATASETS))
    ap.add_argument('--limit', type=int, default=None, help='先頭N営業日（ドライラン用）')
    ap.add_argument('--start', default=None, help='開始日を上書き')
    ap.add_argument('--end', default=None, help='終了日を上書き')
    args = ap.parse_args()

    path, date_param, default_start, mode = DATASETS[args.dataset]
    interval = interval_for(args.dataset)
    start = args.start or default_start

    try:
        days = load_business_days(start, args.end)
    except JQuantsError as e:
        logging.error(str(e))
        return False

    if mode == 'friday':
        # 週末残高は金曜基準。月曜〜木曜は 200 で 0 件しか返らない
        before = len(days)
        days = [d for d in days
                if datetime.strptime(d, '%Y-%m-%d').weekday() == 4]
        logging.info(f'friday モード: {before:,} 営業日 → {len(days):,} 金曜')

    if args.limit:
        days = days[:args.limit]
        logging.info(f'DRY-RUN: 先頭 {len(days)} 日のみ')

    if not days:
        logging.error('対象日が0件')
        return False

    logging.info('=' * 60)
    logging.info(f'{args.dataset} [{mode}]: {len(days):,} 日  {days[0]}..{days[-1]}')
    logging.info(f'  レート {60 / interval:.0f}/分 → 最短 {len(days) * interval / 60:.0f} 分'
                 f'（設定合計 {check_budget()}/分・同時実行は Premium 500/分以内に収める）')
    logging.info('=' * 60)

    client = Client(min_interval=interval)
    try:
        if mode == 'range':
            got, skipped, empty = fetch_range(client, args.dataset, path,
                                              days[0], days[-1])
        else:
            got, skipped, empty = fetch_by_date(client, args.dataset, path, days,
                                                date_param=date_param)
    except JQuantsError as e:
        logging.error(f'取得中断: {e}')
        logging.error('再実行すれば取得済みの日はスキップして続きから再開します')
        return False

    logging.info(f'✅ {args.dataset}: 取得{got} / キャッシュ{skipped} / 空{empty}')
    logging.info(f'API呼び出し {client.n_calls:,} 回 / 429 {client.n_429} 回')
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
