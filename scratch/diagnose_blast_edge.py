import os, sys, pickle, math
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.hunt_institutional_blast import df_ep

print(f"Total analyzed blasts: {len(df_ep)}")
monsters = df_ep[df_ep["fwd_ret_21"] >= 15.0]
failures = df_ep[df_ep["fwd_ret_21"] < 0]

print(f"Monsters (>= +15% in 21d): {len(monsters)} ({len(monsters)/len(df_ep)*100:.1f}%)")
print(f"Failures (< 0% in 21d):    {len(failures)} ({len(failures)/len(df_ep)*100:.1f}%)")

print("\n--- COMPARISON OF KEY METRICS ---")
metrics = ["rvol", "range_ratio", "daily_ret", "pct_from_52w"]
for m in metrics:
    m_val = monsters[m].median()
    f_val = failures[m].median()
    print(f"• {m:15s}: Monsters={m_val:5.2f} | Failures={f_val:5.2f}")

