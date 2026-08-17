"""日付単位で引く系統（fins/summary, markets/breakdown …）の共通取得ロジック。

設計の要点:
  - **1営業日 = 1ファイル**（data/jquants/{dataset}/{YYYY}/{YYYY-MM-DD}.json）。
    取得済みはスキップするだけで再開できるので、数時間のジョブが中断しても捨てない。
  - 0件の日も**空ファイルとして記録する**。そうしないと「まだ取っていない日」と
    「取ったが元々データが無い日」を区別できず、毎回引き直すことになる。
    （祝日取引日は 1_fetch_calendar_master.py の営業日判定で先に除外済み）
  - 年次 parquet への圧縮は 4_compact_to_parquet.py が別途行う（取得と変換の分離）。
"""
import os
import json
import time
import logging

from _jq_client import JQuantsError

DATA_ROOT = os.path.join('data', 'jquants')


def day_path(dataset, date):
    return os.path.join(DATA_ROOT, dataset, date[:4], f'{date}.json')


def fetch_by_date(client, dataset, path, days, date_param='date',
                  extra_params=None, log_every=100):
    """営業日リストを順に叩き、1日1ファイルで保存する。

    戻り値: (取得した日数, スキップした日数, 空だった日数)
    """
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')

    got = skipped = empty = 0
    total = len(days)
    t0 = time.monotonic()

    for i, date in enumerate(days, 1):
        out = day_path(dataset, date)
        if os.path.exists(out):
            skipped += 1
            continue

        params = dict(extra_params or {})
        params[date_param] = date
        rows = client.get(path, params)

        # 未来日の空応答はキャッシュしない。書くとその日が到来しても
        # 「取得済み」と見なされ、二度と埋まらなくなる
        if not rows and date > today:
            empty += 1
            continue

        os.makedirs(os.path.dirname(out), exist_ok=True)
        # 空でも書く（過去日なら「元々データ無し」が確定するため、未取得と区別する）
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        got += 1
        if not rows:
            empty += 1

        if got and (got % log_every == 0 or i == total):
            el = time.monotonic() - t0
            rate = got / el if el else 0
            eta = (total - i) / rate / 60 if rate else 0
            logging.info(f'  {dataset} {i}/{total}  {date}  '
                         f'取得{got} skip{skipped} 空{empty}  残り約{eta:.0f}分')

    return got, skipped, empty


def fetch_range(client, dataset, path, start, end, params_key=('from', 'to')):
    """from/to で一括取得する系統（investor-types）。ページングは client が辿る。

    日付パラメータが効かず期間指定でしか引けないため、by-date とは別扱いにする。
    """
    out = os.path.join(DATA_ROOT, dataset, f'{start}_{end}.json')
    if os.path.exists(out):
        logging.info(f'  {dataset}: キャッシュ済み')
        return 0, 1, 0

    p = {params_key[0]: start, params_key[1]: end}
    rows = client.get(path, p)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False)
    logging.info(f'  {dataset}: {len(rows):,} 件  {start}..{end}')
    return 1, 0, (1 if not rows else 0)


def load_business_days(start=None, end=None):
    """1_fetch_calendar_master.py が保存したカレンダーから営業日を得る。

    🔴 end を省いたときは **今日** で止める。カレンダーは2年先（2027-12-31）まで
    入っているため、上限を切らないと未来日まで取得しに行き、しかも空応答を
    キャッシュとして書いてしまう。そうなるとその日が実際に到来しても
    「取得済み」と見なされ、二度と埋まらない。
    """
    from datetime import datetime
    cal_path = os.path.join(DATA_ROOT, 'calendar.json')
    if not os.path.exists(cal_path):
        raise JQuantsError('先に 1_fetch_calendar_master.py を実行してください '
                           f'（{cal_path} がありません）')
    with open(cal_path, encoding='utf-8') as f:
        cal = json.load(f)
    # 判定は 1_fetch_calendar_master.py と同じ定義を使う
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        '_cal', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '1_fetch_calendar_master.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    today = datetime.now().strftime('%Y-%m-%d')
    days = mod.business_days(cal, start or '0000-00-00', end or today)
    return days
