"""8_daily_update.py

J-Quants の**日次差分**を取って R2 の `jp/jquants/` を更新する。

1〜7 のスクリプトが「18年分を一度に取り切る」履歴投入だったのに対し、
これは毎営業日の追記専用。GitHub Actions から 16:40 JST に走らせる。

## Light プランで取れる系統（2026-08-16 実測）

    bars_daily      /equities/bars/daily          4本値（16:30 頃に確定）
    fins_summary    /fins/summary                 財務情報（DiscDate/DiscTime）
    earnings_date   /fins/earnings-date           決算発表予定日
    master          /equities/master              上場銘柄一覧（月末のみ追記）
    investor_types  /equities/investor-types      投資部門別（週次）
    topix           /indices/bars/daily/topix     TOPIX
    calendar        /markets/calendar             取引カレンダー

  403 になる（Standard 以上が必要）:
    fins/details, fins/dividend, markets/breakdown, short-ratio,
    short-sale-report, margin-interest, margin-alert, indices,
    derivatives/*, edinet/*
  → これらの R2 上の既存ファイルは**触らない**。プランを戻せば 1〜7 で続きから
    取れる（キャッシュ済みの日はスキップされる）。

## 🔴 Light は5年ローリング窓

  calendar は Light だと 2021-08〜 の 2,329 日しか返らない。R2 の calendar.json は
  2008-2027 を収録しているので、**素朴に上書きすると履歴が消える**。
  必ず Date でマージする（`update_calendar`）。
  investor_types / master_monthly も単一ファイルの積み上げなので追記のみ。

## レート

  Light はアカウント全体 60 req/分。この処理は1日あたり十数リクエストしか
  投げないので上限は問題にならないが、間隔は _jq_rates.py の設定に従う。

使い方:
  python scripts/jp/jquants/8_daily_update.py                # ドライラン
  python scripts/jp/jquants/8_daily_update.py --execute
  python scripts/jp/jquants/8_daily_update.py --execute --lookback 30
"""
import os
import sys
import io
import json
import argparse
import logging
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from _jq_client import Client, JQuantsError
from _jq_rates import DAILY_INTERVAL
from common.r2 import create_s3_client

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

PREFIX = 'jp/jquants'

# dataset -> (APIパス, 日付パラメータ, R2 の年次パス, 応答側の日付列)
BYDATE = {
    'bars_daily':    ('/equities/bars/daily', 'date', 'bars_daily/{year}.parquet', 'Date'),
    'fins_summary':  ('/fins/summary',        'date', 'fins_summary/{year}.parquet', 'DiscDate'),
    'earnings_date': ('/fins/earnings-date',  'date', 'earnings_date/{year}.parquet', 'PubDate'),
}


# 🔴 Light では応答に含まれない列（列が null になるのではなく、キーごと落ちる）。
# /equities/bars/daily は Premium 44列に対し Light は 18列しか返さない。
# 差の26列は**前場(M*)・後場(A*)の四本値**で、Premium 期間は94%充足していた。
# 列自体は R2 のファイル構成を保つため欠測で埋める（列が消えると研究側の
# 読み込みが壊れるため）。Light 期間の M*/A* は「欠測」であって「値が無い日」
# ではない点に注意。docs/JQUANTS_DATA.md にも記載。
#
# ExRT（権利落ち率）はここに入れない。Premium でも 158/666,466 行しか
# 埋まっていない元々疎な列で、プラン差ではない。
PLAN_GATED_COLUMNS = {
    'bars_daily': {
        'MO', 'MH', 'ML', 'MC', 'MUL', 'MLL', 'MVo', 'MVa',
        'MAdjO', 'MAdjH', 'MAdjL', 'MAdjC', 'MAdjVo',
        'AO', 'AH', 'AL', 'AC', 'AUL', 'ALL', 'AVo', 'AVa',
        'AAdjO', 'AAdjH', 'AAdjL', 'AAdjC', 'AAdjVo',
    },
}


# 🔴 R2 の履歴が **bulk CSV 由来**の系統。欠測が NaN で入っている一方、
# API(JSON) は空文字 `''` を返すため、そのまま追記すると同じ列に2種類の
# 欠測表現が混ざる（earnings_date.SchDate = 発表予定日が未定の行で実際に発生）。
# 追記側を None に寄せて揃える。
#
# 他の系統は履歴も API(JSON) 由来なので `''` で統一されている。逆向きに
# 変換すると既存とずれるため、ここに挙げたものだけを対象にする。
EMPTY_AS_NULL = {'earnings_date'}


def bucket():
    return os.environ.get('R2_BUCKET_NAME', 'stock-data')


def r2_get(key):
    """R2 からバイト列を取る。存在しなければ None。

    boto3 クライアントは呼び出しごとに新規生成する（再利用は過去に不具合）。
    """
    from botocore.exceptions import ClientError
    s3 = create_s3_client()
    try:
        return s3.get_object(Bucket=bucket(), Key=key)['Body'].read()
    except ClientError as e:
        # R2 は NoSuchKey ではなく 404 を返すことがあるのでコードで判定する。
        # 「鍵が無い」以外のエラー（権限・接続）を None に潰すと、
        # 既存ファイルを空と誤認して上書きしかねないため必ず再送出する
        if e.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None
        raise


def r2_put(key, data):
    s3 = create_s3_client()
    s3.put_object(Bucket=bucket(), Key=key, Body=data)


def read_parquet(key):
    raw = r2_get(key)
    return None if raw is None else pd.read_parquet(io.BytesIO(raw))


def write_parquet(df, key, execute):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    mb = buf.tell() / 1024 / 1024
    logging.info(f'  {"→ PUT" if execute else "→ 予定"} {key}  '
                 f'{len(df):,}行 × {len(df.columns)}列  {mb:.1f}MB')
    if execute:
        r2_put(key, buf.getvalue())


def align(old, new, name):
    """新規フレームを既存の列構成・型に合わせる。

    JSON 由来なので 4_compact_to_parquet.py のような数値化は不要（API が型を
    返す）。ただし「その日はどの銘柄も空だった列」が object になって既存の
    float 列とぶつかることがあるため、既存の dtype に寄せる。
    """
    missing = [c for c in old.columns if c not in new.columns]
    extra = [c for c in new.columns if c not in old.columns]
    if extra:
        # 列が増えるのは API 仕様変更。落とさず載せるが、必ず気づけるよう警告する
        logging.warning(f'  ⚠ {name}: 既存に無い列 {extra} — そのまま追加します')
    if missing:
        known = set(missing) <= PLAN_GATED_COLUMNS.get(name, set())
        msg = (f'  {name}: 応答に無い列 {len(missing)}件 — Light では取得不可'
               f'（既知）。欠測として埋めます'
               if known else
               f'  ⚠ {name}: 応答に無い列 {missing} — 欠測として埋めます')
        (logging.info if known else logging.warning)(msg)
        for c in missing:
            new[c] = None
    if name in EMPTY_AS_NULL:
        for c in new.columns:
            if new[c].dtype == object:
                new[c] = new[c].map(lambda v: None if v == '' else v)

    for c in old.columns:
        if c in new.columns and new[c].dtype != old[c].dtype:
            try:
                new[c] = new[c].astype(old[c].dtype)
            except (TypeError, ValueError):
                # 型を寄せられない場合は concat 側の昇格に任せる（欠落より安全）
                logging.info(f'  {name}.{c}: dtype {new[c].dtype} → '
                             f'{old[c].dtype} に寄せられず、そのまま結合')
    return new[[c for c in old.columns] + extra]


def business_days(cal, start, end):
    """HolDiv '1'(営業日) と '2'(半日立会) のみ。

    '3' は祝日取引日で株式の立会が無く、bars/daily が 0 件になる。
    """
    return sorted(d['Date'] for d in cal
                  if d.get('HolDiv') in ('1', '2') and start <= d['Date'] <= end)


def update_calendar(client, execute):
    """カレンダーを取得し、R2 の既存と **Date でマージ** して戻す。

    🔴 Light は直近5年しか返さない。上書きすると 2008-2021 が消える。
    """
    key = f'{PREFIX}/calendar.json'
    rows = client.get('/markets/calendar')
    new = {d['Date']: d for d in rows}

    raw = r2_get(key)
    old = {d['Date']: d for d in json.loads(raw)} if raw else {}
    merged = dict(old)
    merged.update(new)               # 同じ日は新しい応答を採る（訂正の反映）
    if len(merged) < len(old):
        raise RuntimeError('カレンダーがマージ後に減少しました（異常）')

    added = len(merged) - len(old)
    logging.info(f'calendar: 既存{len(old):,} + 取得{len(new):,} → {len(merged):,} '
                 f'(+{added})')
    if added and execute:
        body = json.dumps([merged[k] for k in sorted(merged)],
                          ensure_ascii=False).encode('utf-8')
        r2_put(key, body)
    return [merged[k] for k in sorted(merged)]


def update_bydate(client, name, days, execute):
    """日付単位の系統を、営業日ごとに追記する。

    既に R2 に入っている日は叩かない。取得できた日は**その日の行を差し替える**
    （訂正が入っても追随できる）。ただし応答が 0 件で既存に行がある場合は
    既存を残す — API 側の一時的な欠落でデータを消さないため。
    """
    path, date_param, key_tpl, date_col = BYDATE[name]
    changed = 0

    for year in sorted({d[:4] for d in days}):
        key = f'{PREFIX}/{key_tpl.format(year=year)}'
        df = read_parquet(key)
        if df is None:
            # 年が変わった最初の実行。前年のファイルから**列と dtype だけ**を
            # 引き継いだ空フレームを作る。ここで前年を土台にしないと、
            # 1月最初の応答だけから列構成が決まってしまい、その日たまたま
            # 全銘柄 null だった列が落ちて前年とスキーマがずれる。
            prev = read_parquet(f'{PREFIX}/{key_tpl.format(year=str(int(year) - 1))}')
            if prev is None:
                logging.error(f'  ✗ {name}: {key} も前年のファイルも R2 に'
                              f'ありません。1〜5 のフルパスで作成してください')
                return False
            df = prev.iloc[0:0].reset_index(drop=True)
            logging.info(f'{name} {year}: 新年のファイルを前年の構成で新規作成'
                         f'（{len(df.columns)}列）')
        have = set(df[date_col].astype(str))
        todo = [d for d in days if d[:4] == year and d not in have]
        if not todo:
            logging.info(f'{name} {year}: 追加なし（{len(df):,}行 / 最新 '
                         f'{max(have) if have else "-"}）')
            continue

        logging.info(f'{name} {year}: {len(todo)} 日 未取得 {todo}')
        parts = []
        for d in todo:
            rows = client.get(path, {date_param: d})
            if not rows:
                logging.warning(f'  {name} {d}: 0件')
                continue
            parts.append(pd.DataFrame(rows))
        if not parts:
            continue

        new = align(df, pd.concat(parts, ignore_index=True), name)
        out = pd.concat([df, new], ignore_index=True)
        out = out.sort_values([date_col]).reset_index(drop=True)
        logging.info(f'  {name} {year}: {len(df):,} → {len(out):,}行 '
                     f'(+{len(out) - len(df):,})')
        write_parquet(out, key, execute)
        changed += 1
    return True


def update_master(client, cal, today, execute):
    """月末営業日のスナップショットだけ追記する（既存の月次系列を保つ）。"""
    key = f'{PREFIX}/master_monthly.parquet'
    df = read_parquet(key)
    if df is None:
        logging.error(f'  ✗ master: {key} がありません')
        return False

    # 直近13か月ぶんの「その月の最終営業日」を求め、未収録のものを埋める
    start = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=400)
             ).strftime('%Y-%m-%d')
    days = business_days(cal, start, today)
    month_end = {}
    for d in days:
        month_end[d[:7]] = d
    # 当月はまだ月末が来ていないので対象外（月中のスナップショットを混ぜない）
    month_end.pop(today[:7], None)

    have = set(df['Date'].astype(str))
    todo = sorted(d for d in month_end.values() if d not in have)
    if not todo:
        logging.info(f'master: 追加なし（{len(df):,}行 / 最新 {max(have)}）')
        return True

    logging.info(f'master: {len(todo)} 月末 未取得 {todo}')
    parts = [pd.DataFrame(client.get('/equities/master', {'date': d}))
             for d in todo]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return True
    new = align(df, pd.concat(parts, ignore_index=True), 'master')
    out = pd.concat([df, new], ignore_index=True).sort_values(['Date', 'Code'])
    out = out.reset_index(drop=True)
    logging.info(f'  master: {len(df):,} → {len(out):,}行')
    write_parquet(out, key, execute)
    return True


def update_investor_types(client, today, execute):
    """週次の投資部門別。単一ファイルに追記する（date が効かないので from/to）。"""
    key = f'{PREFIX}/investor_types.parquet'
    df = read_parquet(key)
    if df is None:
        logging.error(f'  ✗ investor_types: {key} がありません')
        return False
    last = str(df['PubDate'].max())
    start = (datetime.strptime(last, '%Y-%m-%d') + timedelta(days=1)
             ).strftime('%Y-%m-%d')
    if start > today:
        logging.info(f'investor_types: 追加なし（最新 {last}）')
        return True

    rows = client.get('/equities/investor-types', {'from': start, 'to': today})
    if not rows:
        logging.info(f'investor_types: {start}..{today} は 0 件（未公表）')
        return True
    new = align(df, pd.DataFrame(rows), 'investor_types')
    out = pd.concat([df, new], ignore_index=True).sort_values('PubDate')
    out = out.reset_index(drop=True)
    logging.info(f'  investor_types: {len(df):,} → {len(out):,}行')
    write_parquet(out, key, execute)
    return True


def update_topix(client, execute):
    """TOPIX。date パラメータが効かず全期間（Light は5年）を返すので毎回マージ。

    R2 の `indices/{year}.parquet`（Code='0000'）と重複するが、indices は
    Standard 以上でしか引けない。Light 期間中はこちらが唯一の指数系列になる。
    """
    key = f'{PREFIX}/topix.parquet'
    rows = client.get('/indices/bars/daily/topix')
    if not rows:
        logging.warning('topix: 0件')
        return True
    new = pd.DataFrame(rows)
    df = read_parquet(key)
    if df is not None:
        new = align(df, new, 'topix')
        out = pd.concat([df, new], ignore_index=True)
        out = out.drop_duplicates(subset=['Date'], keep='last')
        out = out.sort_values('Date').reset_index(drop=True)
        if len(out) < len(df):
            raise RuntimeError('topix がマージ後に減少しました（異常）')
    else:
        out = new.sort_values('Date').reset_index(drop=True)
        logging.info('topix: 新規作成')
    logging.info(f'  topix: {len(out):,}行  {out["Date"].min()}..{out["Date"].max()}')
    write_parquet(out, key, execute)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='実際に R2 へ書く')
    ap.add_argument('--lookback', type=int, default=10,
                    help='何日前まで遡って未取得日を探すか（既定10日）')
    ap.add_argument('--only', default=None, help='カンマ区切りで系統を限定')
    args = ap.parse_args()

    today = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=args.lookback)).strftime('%Y-%m-%d')

    # Light はアカウント全体 60/分。日次差分は十数リクエストしか投げないので
    # 30/分（半分の margin）で走らせる。_jq_rates.py の RATES_PER_MIN は
    # Premium 用の 120/分なので、こちらでは使わない
    client = Client(min_interval=DAILY_INTERVAL)

    logging.info('=' * 60)
    logging.info(f'J-Quants 日次更新  {start} .. {today}  '
                 f'{"EXECUTE" if args.execute else "DRY-RUN"}')
    logging.info('=' * 60)

    only = {s.strip() for s in args.only.split(',')} if args.only else None

    def want(n):
        return only is None or n in only

    try:
        cal = update_calendar(client, args.execute) if want('calendar') else None
        if cal is None:
            raw = r2_get(f'{PREFIX}/calendar.json')
            cal = json.loads(raw) if raw else []
        days = business_days(cal, start, today)
        if not days:
            logging.info(f'{start}..{today} に営業日がありません（休場）')
            return True
        logging.info(f'対象営業日 {len(days)} 日: {days[0]}..{days[-1]}')

        ok = True
        for name in BYDATE:
            if want(name):
                ok &= update_bydate(client, name, days, args.execute)
        if want('master'):
            ok &= update_master(client, cal, today, args.execute)
        if want('investor_types'):
            ok &= update_investor_types(client, today, args.execute)
        if want('topix'):
            ok &= update_topix(client, args.execute)
    except JQuantsError as e:
        logging.error(f'API エラーで中断: {e}')
        return False

    logging.info(f'API呼び出し {client.n_calls:,} 回 / 429 {client.n_429} 回')
    if not args.execute:
        logging.info('DRY-RUN でした。実投入は --execute を付けてください')
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
