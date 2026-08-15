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
    ----------------------------------------
    合計          417/分  < Premium 500
"""

# アカウント全体の上限（Premium）
PLAN_LIMIT_PER_MIN = 500

# 実際に使うレート（req/分）。合計が PLAN_LIMIT_PER_MIN を超えないこと。
RATES_PER_MIN = {
    'master':        120,
    'delisted_bars': 120,
    'breakdown':     120,
    # /fins/summary はプランに関わらず 60/分の個別上限。margin を見て 57
    'fins_summary':   57,
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
    """設定値がプラン上限に収まっているかを確認する（起動時の自己点検用）。"""
    total = sum(RATES_PER_MIN.values())
    if total > PLAN_LIMIT_PER_MIN:
        raise ValueError(
            f'RATES_PER_MIN の合計 {total}/分 が Premium 上限 '
            f'{PLAN_LIMIT_PER_MIN}/分 を超えています')
    return total
