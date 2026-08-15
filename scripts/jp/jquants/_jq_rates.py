"""J-Quants のレート制限（公式仕様 https://jpx-jquants.com/ja/spec/rate-limits）。

## プラン別（アカウント全体・リクエスト/分）
    Free 5 / Light 60 / Standard 120 / **Premium 500**

## エンドポイント個別（プランに関わらず適用・リクエスト/分）
    /v2/fins/summary  60
    /v2/fins/details  60
    分足・ティック(アドオン) 60 ／ TDnet(アドオン) 100
  これらは**プラン上限とは独立**に効く。

## 超過時
    429 Too Many Requests。**大幅超過を続けると5分程度アクセスが完全遮断される**ため、
    上限に張り付かせず margin を取る。Retry-After ヘッダは仕様に記載が無い。

🔴 過去の実測メモ「master は間隔6秒でも5回目に 429」は **Free プラン時代のもの**。
   Free は 5 req/分なので 6秒間隔(=10 req/分)なら 429 になって当然で、
   Premium には当てはまらない。プラン変更時はこの手の経験則を必ず見直すこと。

## 本パイプラインの配分

同時に走らせるジョブの合計がアカウント上限を超えないよう、ここで一元管理する。
安全率は 0.7 前後（遮断のペナルティが5分と重いため）。

    fins_summary   57/分  ← エンドポイント個別上限 60 に対して margin
    breakdown     120/分
    delisted_bars 120/分
    master        120/分
    short_ratio   120/分
    ----------------------------------------
    合計          537/分  > Premium 500 ⚠

⚠ 全ジョブを**同時に**走らせると上限を超える。実際には master と delisted_bars は
  短時間で終わるため、同時実行するのは2〜3ジョブ。`check_budget()` は設定の
  合計を返すだけにして、同時実行の制御は運用側（起動の順序）で行う。
"""

# アカウント全体の上限（Premium）
PLAN_LIMIT_PER_MIN = 500

# 実際に使うレート（req/分）。合計が PLAN_LIMIT_PER_MIN を超えないこと。
RATES_PER_MIN = {
    'master':          120,
    'delisted_bars':   120,
    'breakdown':       120,
    'short_ratio':     120,
    'dividend':        120,
    'margin_interest': 120,
    'margin_alert':    120,
    'investor_types':  120,
    # /fins/summary と /fins/details はプランに関わらず 60/分の個別上限。margin を見て 57
    'fins_summary':     57,
    'fins_details':     57,
}

# エンドポイント個別上限（プランに関わらず適用）
ENDPOINT_LIMIT_PER_MIN = {
    '/fins/summary': 60,
    '/fins/details': 60,
}


def interval_for(job):
    """ジョブ名から呼び出し間隔（秒）を返す。"""
    rpm = RATES_PER_MIN[job]
    return 60.0 / rpm


def check_budget():
    """全ジョブのレート合計を返す（起動時のログ用）。

    合計はプラン上限を超え得る。全ジョブを同時に走らせない前提のため
    例外にはしない（超えたら 429 → バックオフで自動的に減速する）。
    同時に走らせてよい組み合わせは `max_concurrent_rate()` で確認する。
    """
    return sum(RATES_PER_MIN.values())


def budget_ok(jobs):
    """同時に走らせるジョブ名の集合がプラン上限に収まるか。"""
    total = sum(RATES_PER_MIN[j] for j in jobs)
    return total <= PLAN_LIMIT_PER_MIN, total
