"""
verify_backfill.py

data/backfill/r2/.../core/{2023,2024}/{sym}.json（生成済み）を検証する。
  - レコード数・RS埋まり数・日付レンジ
  - RS が [1,99] に収まるか
  - 2024前半(新規RS) と 2024後半(既存RS) の連続性（大きな段差が無いか）
"""
import os, sys, json, glob
import statistics as st

CORE = os.path.join("data", "backfill", "r2", "stocks", "daily", "core")


def load(sym, year):
    p = os.path.join(CORE, str(year), f"{sym}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def check(sym):
    print(f"\n### {sym}")
    for year in (2023, 2024):
        d = load(sym, year)
        if d is None:
            print(f"  {year}: (no local file)")
            continue
        rows = d['data']
        rs = [r['rs_percentile'] for r in rows if r.get('rs_percentile') is not None]
        bad = [r for r in rs if not (1 <= r <= 99)]
        rng = f"{rows[0]['date']}..{rows[-1]['date']}"
        print(f"  {year}: rec={len(rows)} rs={len(rs)} range={rng} "
              f"rs[min/med/max]={min(rs):.1f}/{st.median(rs):.1f}/{max(rs):.1f} "
              f"out_of_range={len(bad)}")
        if year == 2024:
            h1 = [r['rs_percentile'] for r in rows if r['date'] < '2024-06-01' and r.get('rs_percentile') is not None]
            h2 = [r['rs_percentile'] for r in rows if r['date'] >= '2024-06-01' and r.get('rs_percentile') is not None]
            if h1 and h2:
                print(f"       2024 H1(new) med={st.median(h1):.1f}  H2(existing) med={st.median(h2):.1f}")


def main():
    syms = sys.argv[1:] or ['AAPL', 'MSFT', 'NVDA', 'AMD', 'TSLA', 'META']
    n23 = len(glob.glob(os.path.join(CORE, '2023', '*.json')))
    n24 = len(glob.glob(os.path.join(CORE, '2024', '*.json')))
    print(f"local built files: 2023={n23}  2024={n24}")
    for s in syms:
        check(s)


if __name__ == "__main__":
    main()
