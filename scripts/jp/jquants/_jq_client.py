"""J-Quants V2 API の共有クライアント。

🔴 秘密情報はこのファイルに書かない。`.env` の `JQUANTS_API_KEY` を読む。
   キーは `x-api-key` ヘッダに直接載るため、ログ・例外文字列に混ぜないこと。
   （`_headers()` の戻り値を print / logging しない）

V2 の要点（2026-08-15 実測）:
  - V1 は 410 で完全終了。トークン取得エンドポイントは廃止され、
    ダッシュボード発行の API キーをヘッダに載せるだけになった。
  - ベースは https://api.jquants.com/v2

レート制限は `_jq_rates.py` に一元化してある（公式仕様ベース）。
Premium は 500 req/分（アカウント全体）で、`/fins/summary` と `/fins/details` のみ
プランに関わらず 60 req/分の個別上限。呼び出し側が `min_interval` を渡す。
429 は指数バックオフで待つ（遮断が5分程度あり得るため上限 360 秒）。

契約範囲外の日付を指定すると 400 が返り、**本文に有効期間が書かれている**:
  {"message": "Your subscription covers the following dates: 2006-08-15 ~ ."}
"""
import os
import time
import logging

import requests
from dotenv import load_dotenv

ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), '.env')
BASE = 'https://api.jquants.com/v2'

# 実測でデータが存在する下限。契約窓（2006-08-15〜）より新しいので、
# 実際に効いているのはこちら。詳細は docs/JQUANTS_DATA.md
PRICE_START = '2008-05-07'


class JQuantsError(RuntimeError):
    pass


class Client:
    """J-Quants V2 クライアント。ページングを辿って全件返す。"""

    def __init__(self, min_interval=3.0, max_retries=5, timeout=60):
        load_dotenv(ENV_PATH)
        self.apikey = (os.environ.get('JQUANTS_API_KEY') or '').strip()
        if not self.apikey:
            raise JQuantsError(
                f'.env に JQUANTS_API_KEY がありません: {ENV_PATH}\n'
                'J-Quants ダッシュボードで API キーを発行して設定してください。')
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_call = 0.0
        self.n_calls = 0
        self.n_429 = 0
        # requests.Session は接続を使い回すだけで、boto3 のような
        # 認証状態を持たないため再利用して問題ない
        self._session = requests.Session()

    def _headers(self):
        # 🔴 この戻り値をログに出さないこと
        return {'x-api-key': self.apikey}

    def _pace(self):
        """前回呼び出しから min_interval 秒あけるまで待つ。"""
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def get(self, path, params=None):
        """1エンドポイントを叩き、pagination_key を辿って全レコードを返す。

        戻り値: list[dict]
        例外: JQuantsError（リトライしても回復しなかった場合）
        """
        p = dict(params or {})
        out = []
        while True:
            body = self._get_once(path, p)
            key = next((k for k in body if isinstance(body.get(k), list)), None)
            if key is not None:
                out.extend(body[key])
            nxt = body.get('pagination_key')
            if not nxt:
                return out
            p['pagination_key'] = nxt

    def _get_once(self, path, params):
        last = None
        for attempt in range(self.max_retries):
            self._pace()
            try:
                r = self._session.get(BASE + path, headers=self._headers(),
                                      params=params, timeout=self.timeout)
            except requests.RequestException as e:
                last = f'network: {type(e).__name__}'
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            self.n_calls += 1

            if r.status_code == 200:
                return r.json()

            if r.status_code == 429:
                # レート制限。公式仕様では「大幅超過を続けると5分程度アクセスが
                # 完全遮断される」ため、上限は遮断時間より長い 360 秒まで伸ばす
                # （120 秒で諦めると遮断明けを待てずにジョブが落ちる）
                self.n_429 += 1
                back = min(360, 10 * (2 ** attempt))
                logging.warning(f'  429 {path} params={_safe(params)} '
                                f'-> {back}s 待機 (attempt {attempt + 1})')
                time.sleep(back)
                continue

            if 500 <= r.status_code < 600:
                last = f'{r.status_code}: {r.text[:150]}'
                time.sleep(min(60, 5 * (attempt + 1)))
                continue

            # 4xx は再試行しても同じ。本文に理由が入っている（契約範囲外など）
            raise JQuantsError(f'{r.status_code} {path} params={_safe(params)}: '
                               f'{r.text[:300]}')

        raise JQuantsError(f'{path} params={_safe(params)} が '
                           f'{self.max_retries} 回失敗: {last}')


def _safe(params):
    """params をログ用に整形（キーは params に載らないが念のため除去）。"""
    return {k: v for k, v in (params or {}).items() if k != 'x-api-key'}
