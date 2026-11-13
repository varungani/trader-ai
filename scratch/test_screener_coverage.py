import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.screener import select_deep_score_universe

res = select_deep_score_universe(preset="extended", top_n=15)
print("Preset:", res["preset"])
print("Scanned Universe Size:", res["universe_size"])
print("All Screened Count:", len(res["all_screened"]))
print("Top 10 Screened Picks:")
for s in res["screened"][:10]:
    print(f"  {s['ticker']}: score={s['screen_score']} | rvol={s['rvol']}x | pat={s['setup_pattern']} | px=Rs.{s['price']} | 1m={s['ret_1m_pct']}%")

print("\nBottom 5 Screened Stocks:")
for s in res["all_screened"][-5:]:
    print(f"  {s['ticker']}: score={s['screen_score']} | rvol={s['rvol']}x | pat={s['setup_pattern']} | px=Rs.{s['price']}")
