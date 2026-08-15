"""3_fetch_bydate_series.py

日付単位で引く系統をまとめて取得する。

  fins_summary … /fins/summary   財務情報。**DiscDate / DiscTime = 決算の実発表日時**。
                 Premium の必須理由②。現行パネルの earningsDate は 2008-2013 で
                 充足率 17-39% しかなく残りは「会計期末+45日」の近似で、
                 その代償が実測で GEO -281pp（研究側ログ）。
  breakdown    … /markets/breakdown  売買内訳。信用新規売りと買い戻しが別項目で、
                 51単元(5,100株)の価格規制対象かどうかも分かれる（A-2）。

実測の開始年（2026-08-15）:
  fins_summary 2008-08〜 / breakdown 2015〜
台帳は breakdown を「20年」としているが**実際は11年**で、in-sample 前半には掛からない。

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jq_client import Client, JQuantsError
from _jq_bydate import fetch_by_date, load_business_days

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# dataset -> (APIパス, 日付パラメータ名, 実測の開始日, 呼び出し間隔)
DATASETS = {
    'fins_summary': ('/fins/summary',      'date', '2008-07-01', 3.0),
    # 2015-01〜03 は 200 で 0 件が返る。実データは 2015-04-01 から
    'breakdown':    ('/markets/breakdown', 'date', '2015-04-01', 3.0),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', required=True, choices=sorted(DATASETS))
    ap.add_argument('--limit', type=int, default=None, help='先頭N営業日（ドライラン用）')
    ap.add_argument('--start', default=None, help='開始日を上書き')
    ap.add_argument('--end', default=None, help='終了日を上書き')
    args = ap.parse_args()

    path, date_param, default_start, interval = DATASETS[args.dataset]
    start = args.start or default_start

    try:
        days = load_business_days(start, args.end)
    except JQuantsError as e:
        logging.error(str(e))
        return False

    if args.limit:
        days = days[:args.limit]
        logging.info(f'DRY-RUN: 先頭 {len(days)} 営業日のみ')

    logging.info('=' * 60)
    logging.info(f'{args.dataset}: {len(days):,} 営業日  {days[0]}..{days[-1]}')
    logging.info(f'  間隔{interval}s → 最短 {len(days) * interval / 3600:.1f} 時間')
    logging.info('=' * 60)

    client = Client(min_interval=interval)
    try:
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
