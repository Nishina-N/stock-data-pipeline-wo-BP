"""audit_rs_vintage.py

再生成した RS_scores のヴィンテージを、研究側の受け入れ条件で機械的に検査する。

投入前に必ず通す。R2 には**読みにも書きにも行かない**（ローカル生成物だけを見る）。

## 受け入れ条件（研究側 2026-08-17 の申し送り §6）

  1. フィールド構成が全年で一致（rs_raw は無いこと）
  2. 該当銘柄0件の群が順位付けに参加していないこと / null グループ0件
     → 有効群数が説明可能な形で推移しているかを表示して人が判断する
  3. 年初境界の1日変化が、その年の年内分布の 95 パーセンタイル以下
  4. 隣接年の「1日変化の平均」の比が 0.75〜1.40

3・4 の「1日変化」は、研究側の定義に合わせて
**全群の rs_percentile の1日差の絶対値を、その日について平均したもの**。

使い方:
  python scripts/maintenance/audit_rs_vintage.py
  python scripts/maintenance/audit_rs_vintage.py --root data/regen_rs_scores
"""
import os
import sys
import json
import glob
import argparse
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(message)s')

DEFAULT_ROOT = os.path.join('data', 'regen_rs_scores')


def load_level(root, level):
    """{year: DataFrame(date × group)} と、フィールド集合を返す。"""
    frames = {}
    fields = {}
    for path in sorted(glob.glob(os.path.join(root, level, '*.json'))):
        year = int(os.path.basename(path)[:4])
        with open(path, encoding='utf-8') as f:
            rows = json.load(f)
        if not rows:
            continue
        fields[year] = tuple(sorted(rows[0].keys()))
        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date'])
        frames[year] = df.pivot_table(index='date', columns=level,
                                      values='rs_percentile', aggfunc='last')
    return frames, fields


def daily_change(piv):
    """全群の rs_percentile の1日差の絶対値を、日ごとに平均した系列。"""
    return piv.diff().abs().mean(axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=DEFAULT_ROOT)
    args = ap.parse_args()

    ok_all = True
    for level in ('sector', 'industry'):
        print('=' * 74)
        print(f'■ {level}')
        frames, fields = load_level(args.root, level)
        if not frames:
            print('  生成物なし'); ok_all = False; continue
        years = sorted(frames)

        # --- 条件1: フィールド構成 ---
        uniq = set(fields.values())
        if len(uniq) == 1:
            f = sorted(uniq)[0]
            has_raw = 'rs_raw' in f
            print(f'  1. フィールド構成: 全{len(years)}年で一致 {list(f)}  '
                  f'rs_raw={"あり🔴" if has_raw else "なし ✅"}')
            if has_raw:
                ok_all = False
        else:
            print(f'  1. 🔴 フィールド構成が年で異なる: {uniq}')
            ok_all = False

        # --- 条件2: null グループ / 有効群数の推移 ---
        nulls = sum(int(df.columns.isna().sum()) for df in frames.values())
        print(f'  2. null グループ: {nulls} 件 {"✅" if nulls == 0 else "🔴"}')
        if nulls:
            ok_all = False

        # 全年を1本につなぐ（境界の跳びを測るため）
        allp = pd.concat([frames[y] for y in years]).sort_index()
        allp = allp[~allp.index.duplicated(keep='last')]
        dc = daily_change(allp)

        rows = []
        prev_mean = None
        for y in years:
            piv = frames[y]
            eff = piv.notna().sum(axis=1)
            d = dc[dc.index.year == y]
            mean = float(d.mean())
            ratio = (mean / prev_mean) if prev_mean else np.nan
            # 年初の1営業日目（前年最終日からの変化）
            first = d.index.min()
            jump = float(d.loc[first])
            pct_of_year = float((d <= jump).mean() * 100)
            rows.append({
                'year': y,
                '有効群数': f'{int(eff.median())} ({eff.min()}..{eff.max()})',
                '1日変化': round(mean, 3),
                '前年比': round(ratio, 2) if ratio == ratio else None,
                '年初の跳び': round(jump, 2),
                '年内%タイル': round(pct_of_year, 1),
            })
            prev_mean = mean

        t = pd.DataFrame(rows).set_index('year')
        print(t.to_string())

        # --- 条件3: 年初境界の跳び ---
        bad3 = t[(t['年内%タイル'] > 95) & (t.index > years[0])]
        print(f'  3. 年初の跳びが年内95%タイル超: {len(bad3)}年 '
              f'{"✅" if bad3.empty else "🔴 " + str(list(bad3.index))}')
        if not bad3.empty:
            ok_all = False

        # --- 条件4: 隣接年比 ---
        r = t['前年比'].dropna()
        bad4 = r[(r < 0.75) | (r > 1.40)]
        print(f'  4. 隣接年比が 0.75〜1.40 の外: {len(bad4)}年 '
              f'{"✅" if bad4.empty else "🔴 " + str(bad4.to_dict())}')
        if not bad4.empty:
            ok_all = False

    print('=' * 74)
    print('✅ 全条件パス' if ok_all else '🔴 未達の条件あり（上記参照）')
    return ok_all


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
