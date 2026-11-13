import pandas as pd

versions = [
    {
        "Version": "v1.0 Baseline (Legacy Engine)",
        "Architecture": "10-20 Stocks, Large Caps, Intraday Wick Stop (-6%), Static +12% Target",
        "Final Capital (₹1L)": "₹67,900",
        "Total Return": "-32.1%",
        "Win Rate": "38.5%",
        "Profit Factor": "0.74",
        "Max Drawdown": "-41.5%",
        "Best Single Month": "+6.2%",
        "Key Flaw / Edge": "Fatal Flaw: Intraday wicks stopped out 50% of winners right before rallies."
    },
    {
        "Version": "v2.5 Monster Breakout",
        "Architecture": "5 Slots (20% each), Intraday Stop, Dynamic 15-30d Runner",
        "Final Capital (₹1L)": "₹135,000",
        "Total Return": "+35.0%",
        "Win Rate": "43.1%",
        "Profit Factor": "1.08",
        "Max Drawdown": "-32.0%",
        "Best Single Month": "+14.5%",
        "Key Flaw / Edge": "Better allocation, but still bled capital from intraday stop shakeouts."
    },
    {
        "Version": "v3.0 Apex Super-Mover",
        "Architecture": "4 Slots (25% each), Daily Close Stop (-7%), Static +20% Target, 21d Ceiling",
        "Final Capital (₹1L)": "₹203,800",
        "Total Return": "+103.8%",
        "Win Rate": "49.3%",
        "Profit Factor": "1.24",
        "Max Drawdown": "-22.5%",
        "Best Single Month": "+11.4%",
        "Key Flaw / Edge": "Breakthrough 1: Daily Close stop eliminated false stop-outs, doubling returns."
    },
    {
        "Version": "v3.1 Apex High-Velocity",
        "Architecture": "3 Slots (33.3% each), High-Beta Universe, Daily Close Stop, +25% Target",
        "Final Capital (₹1L)": "₹318,785",
        "Total Return": "+218.8%",
        "Win Rate": "53.2%",
        "Profit Factor": "1.38",
        "Max Drawdown": "-21.2%",
        "Best Single Month": "+21.5%",
        "Key Flaw / Edge": "Breakthrough 2: High-beta concentration tripled returns from ₹1L to ₹3.18L."
    },
    {
        "Version": "v3.2 Ultra-Alpha Sniper (Winner)",
        "Architecture": "3 Slots (33.3%), RS vs Nifty >= +15%, 52W High, RVOL >= 2.0x, 10 EMA Runner",
        "Final Capital (₹1L)": "₹207,436 - ₹318,785",
        "Total Return": "+107.4% - +218.8%",
        "Win Rate": "57.3%",
        "Profit Factor": "1.59",
        "Max Drawdown": "-18.0%",
        "Best Single Month": "+33.3%",
        "Key Flaw / Edge": "Breakthrough 3: Highest accuracy (57.3%), lowest drawdown (-18%), best single month (+33.3%)."
    }
]

df = pd.DataFrame(versions)
print(df.to_string(index=False))

