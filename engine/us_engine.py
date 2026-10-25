"""
US Equities Alpha Engine - Quantitative Momentum & Breakout Scanner
INDmoney / DriveWealth Spot US Equities Universe.

Statutory Model: SEC Section 31 fee + FINRA TAF ($0.000166/share) + FX spread.
Supports Fractional Share Allocation down to 0.001 shares.
Regime Filter: Dual S&P 500 (SPY) & Nasdaq 100 (QQQ) 50-day SMA gate.
"""
from __future__ import annotations

import logging
import os
import pickle
from datetime import datetime, timezone, timedelta
import zoneinfo
import pandas as pd
import numpy as np
import yfinance as yf

from data.db import (
    get_connection,
    create_paper_us_trade,
    close_paper_us_trade,
    get_open_us_paper_trades,
    get_closed_us_paper_trades,
    update_us_paper_trade_stop,
    delete_us_paper_trade,
)

logger = logging.getLogger(__name__)

# Real-time indicative USD/INR conversion rate for Indian accounts
USD_TO_INR_APPROX = 86.50

# 30 Premier US Equities & ETFs available on INDmoney / DriveWealth
INDMONEY_US_UNIVERSE = [
    # Magnificent 7 Tech Titans
    {"symbol": "NVDA", "name": "Nvidia", "sector": "AI & Semiconductors", "tag": "mag7", "display": "NVDA"},
    {"symbol": "AAPL", "name": "Apple", "sector": "Consumer Electronics", "tag": "mag7", "display": "AAPL"},
    {"symbol": "MSFT", "name": "Microsoft", "sector": "Enterprise & Cloud AI", "tag": "mag7", "display": "MSFT"},
    {"symbol": "AMZN", "name": "Amazon", "sector": "E-Commerce & AWS Cloud", "tag": "mag7", "display": "AMZN"},
    {"symbol": "GOOGL", "name": "Alphabet (Google)", "sector": "Search & Cloud AI", "tag": "mag7", "display": "GOOGL"},
    {"symbol": "META", "name": "Meta Platforms", "sector": "Social Media & AI", "tag": "mag7", "display": "META"},
    {"symbol": "TSLA", "name": "Tesla", "sector": "EV & Autonomous Robotics", "tag": "mag7", "display": "TSLA"},
    
    # High-Beta AI & Semiconductor Rockets
    {"symbol": "PLTR", "name": "Palantir Technologies", "sector": "Enterprise AI Software", "tag": "ai_semi", "display": "PLTR"},
    {"symbol": "AVGO", "name": "Broadcom", "sector": "Semiconductors & Custom AI", "tag": "ai_semi", "display": "AVGO"},
    {"symbol": "AMD", "name": "Advanced Micro Devices", "sector": "Data Center & Gaming GPUs", "tag": "ai_semi", "display": "AMD"},
    {"symbol": "QCOM", "name": "Qualcomm", "sector": "Mobile & Edge AI Processors", "tag": "ai_semi", "display": "QCOM"},
    {"symbol": "ARM", "name": "Arm Holdings", "sector": "Semiconductor IP Architecture", "tag": "ai_semi", "display": "ARM"},
    {"symbol": "MU", "name": "Micron Technology", "sector": "HBM Memory & Storage", "tag": "ai_semi", "display": "MU"},
    {"symbol": "TSM", "name": "Taiwan Semiconductor", "sector": "Foundry Monopoly", "tag": "ai_semi", "display": "TSM"},
    {"symbol": "ASML", "name": "ASML Holding", "sector": "EUV Lithography Systems", "tag": "ai_semi", "display": "ASML"},
    
    # High-Velocity Growth & Enterprise Momentum
    {"symbol": "COIN", "name": "Coinbase Global", "sector": "Crypto Financial Ecosystem", "tag": "growth", "display": "COIN"},
    {"symbol": "HOOD", "name": "Robinhood Markets", "sector": "Retail Fintech & Trading", "tag": "growth", "display": "HOOD"},
    {"symbol": "UBER", "name": "Uber Technologies", "sector": "Mobility & Autonomous Delivery", "tag": "growth", "display": "UBER"},
    {"symbol": "APP", "name": "AppLovin", "sector": "AdTech & AI Mobile Monetization", "tag": "growth", "display": "APP"},
    {"symbol": "CRWD", "name": "CrowdStrike", "sector": "Cybersecurity & Cloud Protection", "tag": "growth", "display": "CRWD"},
    {"symbol": "ANET", "name": "Arista Networks", "sector": "Cloud & AI Networking", "tag": "growth", "display": "ANET"},
    {"symbol": "NET", "name": "Cloudflare", "sector": "Edge Computing & Web Infrastructure", "tag": "growth", "display": "NET"},
    {"symbol": "SNOW", "name": "Snowflake", "sector": "Data Cloud & Warehousing", "tag": "growth", "display": "SNOW"},
    {"symbol": "NOW", "name": "ServiceNow", "sector": "Enterprise Workflow Automation", "tag": "growth", "display": "NOW"},
    {"symbol": "SHOP", "name": "Shopify", "sector": "Global Omnichannel Commerce", "tag": "growth", "display": "SHOP"},
    {"symbol": "NFLX", "name": "Netflix", "sector": "Streaming Entertainment", "tag": "growth", "display": "NFLX"},
    
    # Major Market & Sector ETFs
    {"symbol": "QQQ", "name": "Invesco QQQ (Nasdaq 100)", "sector": "US Tech Benchmark ETF", "tag": "etf", "display": "QQQ"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "sector": "Broad Market Benchmark ETF", "tag": "etf", "display": "SPY"},
    {"symbol": "SMH", "name": "VanEck Semiconductor ETF", "sector": "Semiconductor Benchmark ETF", "tag": "etf", "display": "SMH"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "sector": "Small-Cap Benchmark ETF", "tag": "etf", "display": "IWM"},
]


# Official US Stock Market Holidays (NYSE & NASDAQ) - 2025 & 2026
US_MARKET_HOLIDAYS: dict[str, str] = {
    # 2025
    "2025-01-01": "New Year's Day",
    "2025-01-20": "Martin Luther King Jr. Day",
    "2025-02-17": "Presidents' Day (Washington's Birthday)",
    "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day",
    "2025-06-19": "Juneteenth National Independence Day",
    "2025-07-04": "Independence Day",
    "2025-09-01": "Labor Day",
    "2025-11-27": "Thanksgiving Day",
    "2025-12-25": "Christmas Day",

    # 2026
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King Jr. Day",
    "2026-02-16": "Presidents' Day (Washington's Birthday)",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (Observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
}


def get_upcoming_us_holidays(limit: int = 5) -> list[dict]:
    """Returns a list of upcoming official NYSE / NASDAQ holidays mapped to IST."""
    try:
        eastern_tz = zoneinfo.ZoneInfo("America/New_York")
    except Exception:
        eastern_tz = timezone(timedelta(hours=-4))

    today_est = datetime.now(timezone.utc).astimezone(eastern_tz).date()
    upcoming = []
    for dt_str, name in sorted(US_MARKET_HOLIDAYS.items()):
        h_date = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if h_date >= today_est:
            days_away = (h_date - today_est).days
            upcoming.append({
                "date": dt_str,
                "name": name,
                "day_name": h_date.strftime("%A"),
                "formatted": h_date.strftime("%d %b %Y"),
                "days_away": days_away,
                "countdown": "Today" if days_away == 0 else f"In {days_away} days",
                "ist_impact": "Wall Street session halted (07:00 PM – 01:30 AM IST)",
            })
            if len(upcoming) >= limit:
                break
    return upcoming


def get_us_market_status() -> dict:
    """
    Get current US stock market session status (New York Eastern Time vs IST).
    Includes regular trading, pre-market, post-market, and holiday/weekend detection.
    """
    try:
        eastern_tz = zoneinfo.ZoneInfo("America/New_York")
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        eastern_tz = timezone(timedelta(hours=-4))
        ist_tz = timezone(timedelta(hours=5, minutes=30))

    now_utc = datetime.now(timezone.utc)
    now_est = now_utc.astimezone(eastern_tz)
    now_ist = now_utc.astimezone(ist_tz)

    today_est_str = now_est.strftime("%Y-%m-%d")
    weekday = now_est.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    time_minutes = now_est.hour * 60 + now_est.minute

    # Check for official US Holiday first
    if today_est_str in US_MARKET_HOLIDAYS:
        h_name = US_MARKET_HOLIDAYS[today_est_str]
        status = "CLOSED_HOLIDAY"
        badge = f"🔴 US MARKET CLOSED ({h_name.upper()})"
        detail = f"NYSE & NASDAQ closed today for {h_name}. No evening trading session (07:00 PM – 01:30 AM IST)."
        is_regular_open = False
    elif weekday in (5, 6):
        status = "CLOSED_WEEKEND"
        badge = "🔴 US MARKET CLOSED (WEEKEND)"
        detail = "Wall Street resumes Monday 09:30 AM EST (07:00 PM IST)."
        is_regular_open = False
    elif 570 <= time_minutes < 960:
        status = "REGULAR_OPEN"
        badge = "🟢 US MARKET LIVE (REGULAR SESSION)"
        rem_mins = 960 - time_minutes
        hrs, mins = divmod(rem_mins, 60)
        detail = f"NYSE & NASDAQ Active. Closes in {hrs}h {mins}m at 04:00 PM EST (01:30 AM IST)."
        is_regular_open = True
    elif 240 <= time_minutes < 570:
        status = "PRE_MARKET"
        badge = "🟡 PRE-MARKET SESSION"
        rem_mins = 570 - time_minutes
        hrs, mins = divmod(rem_mins, 60)
        detail = f"INDmoney pre-market trading active. Regular open in {hrs}h {mins}m at 09:30 AM EST (07:00 PM IST)."
        is_regular_open = False
    elif 960 <= time_minutes < 1200:
        status = "AFTER_HOURS"
        badge = "🌙 AFTER-HOURS SESSION"
        rem_mins = 1200 - time_minutes
        hrs, mins = divmod(rem_mins, 60)
        detail = f"Post-market earnings reactions active. Session closes in {hrs}h {mins}m at 08:00 PM EST (05:30 AM IST)."
        is_regular_open = False
    else:
        status = "OVERNIGHT_CLOSED"
        badge = "⚪ OVERNIGHT CLOSED"
        detail = "Market opens pre-market at 04:00 AM EST (01:30 PM IST) and regular at 09:30 AM EST (07:00 PM IST)."
        is_regular_open = False

    return {
        "status": status,
        "badge": badge,
        "detail": detail,
        "is_open": is_regular_open,
        "time_est_str": now_est.strftime("%I:%M %p EST (%d %b)"),
        "time_ist_str": now_ist.strftime("%I:%M %p IST (%d %b)"),
    }


def fetch_us_realtime_data() -> dict[str, pd.DataFrame]:
    """
    Fetch recent 100-day daily bars for all INDmoney US universe symbols + SPY + QQQ benchmarks.
    Caches results locally to maintain lightning-fast dashboard responsiveness.
    """
    symbols = [u["symbol"] for u in INDMONEY_US_UNIVERSE]
    benchmarks = ["SPY", "QQQ"]
    all_tickers = sorted(list(set(symbols + benchmarks)))
    
    data = {}
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "us_equities_cache.pkl")

    try:
        raw = yf.download(all_tickers, period="100d", interval="1d", progress=False, group_by="ticker")
        for sym in all_tickers:
            try:
                if sym in raw.columns.levels[0]:
                    df = raw[sym].copy().dropna(subset=["Close", "Volume"])
                    if len(df) >= 20:
                        df.columns = [col.lower() for col in df.columns]
                        data[sym] = df
            except Exception as e:
                logger.warning(f"Failed processing ticker {sym}: {e}")

        # Save valid fetch to cache
        if len(data) >= len(symbols) * 0.7:
            with open(cache_file, "wb") as f:
                pickle.dump(data, f)
    except Exception as e:
        logger.error(f"Error downloading US data: {e}")

    # Fallback to cache if live fetch incomplete
    if len(data) < 5 and os.path.exists(cache_file):
        try:
            with open(cache_file, "rb") as f:
                cached = pickle.load(f)
                for sym in all_tickers:
                    if sym in cached:
                        data[sym] = cached[sym].copy()
            logger.info(f"Loaded {len(data)} tickers from US cache.")
        except Exception as e:
            logger.error(f"Error reading US cache: {e}")

    return data


def analyze_us_market(data: dict[str, pd.DataFrame]) -> dict:
    """
    Perform 4-pillar institutional quant scoring on US Equities.
    Enforces S&P 500 (SPY) and Nasdaq 100 (QQQ) Dual Macro Gates.
    Generates institutional verdicts (BUY / HOLD / SELL / AVOID), fractional share targets,
    and trailing stop levels.
    """
    if "SPY" not in data or len(data["SPY"]) < 20:
        return {"status": "ERROR", "message": "Insufficient S&P 500 (SPY) data for macro analysis."}

    spy_df = data["SPY"].copy()
    spy_close = spy_df["close"]
    spy_sma50 = spy_close.rolling(50).mean()
    spy_ema20 = spy_close.ewm(span=20, adjust=False).mean()

    curr_spy_p = float(spy_close.iloc[-1])
    curr_spy_sma50 = float(spy_sma50.iloc[-1]) if not np.isnan(spy_sma50.iloc[-1]) else curr_spy_p
    curr_spy_ema20 = float(spy_ema20.iloc[-1])

    # QQQ Nasdaq Benchmark
    qqq_pass = True
    curr_qqq_p = curr_spy_p
    curr_qqq_sma50 = curr_spy_sma50
    if "QQQ" in data and len(data["QQQ"]) >= 20:
        qqq_df = data["QQQ"].copy()
        qqq_close = qqq_df["close"]
        qqq_sma50 = qqq_close.rolling(50).mean()
        curr_qqq_p = float(qqq_close.iloc[-1])
        curr_qqq_sma50 = float(qqq_sma50.iloc[-1]) if not np.isnan(qqq_sma50.iloc[-1]) else curr_qqq_p
        qqq_pass = curr_qqq_p >= curr_qqq_sma50

    spy_pass = curr_spy_p >= curr_spy_sma50

    # Macro Regime Evaluation
    if spy_pass and qqq_pass and curr_spy_ema20 > curr_spy_sma50:
        macro_regime = "BULLISH_EXPANSION"
        macro_verdict = "GREEN LIGHT: S&P 500 & Nasdaq in Confirmed Bull Trend (Both > 50 SMA). Institutional Breakouts Enabled."
        entries_allowed = True
    elif spy_pass or qqq_pass:
        macro_regime = "SELECTIVE_CHOP"
        macro_verdict = "YELLOW LIGHT: Selective Market Chop (One index below 50 SMA). Only High-RS Leaders Permitted."
        entries_allowed = True
    else:
        macro_regime = "BEARISH_DOWNTREND"
        macro_verdict = "RED LIGHT: Both SPY & QQQ below 50 SMA. 100% Cash Preservation Locked. Zero Entries Allowed."
        entries_allowed = False

    candidates = []

    for u in INDMONEY_US_UNIVERSE:
        sym = u["symbol"]
        if sym not in data:
            continue
        df = data[sym].copy()
        if len(df) < 25:
            continue

        close = df["close"]
        df["ema10"] = close.ewm(span=10, adjust=False).mean()
        df["ema15"] = close.ewm(span=15, adjust=False).mean()
        df["ema20"] = close.ewm(span=20, adjust=False).mean()
        df["sma50"] = close.rolling(50).mean()
        df["sma200"] = close.rolling(min(200, len(close))).mean()
        df["sma20_vol"] = df["volume"].rolling(20).mean()
        df["rvol"] = df["volume"] / (df["sma20_vol"] + 1e-8)
        df["high20"] = df["high"].rolling(20).max().shift(1)
        df["high10"] = df["high"].rolling(10).max().shift(1)

        # ATR & VCP (Volatility Contraction Pattern)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - close.shift(1)).abs()
        tr3 = (df["low"] - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr5"] = tr.rolling(5).mean()
        df["atr20"] = tr.rolling(20).mean()
        df["vcp_ratio"] = df["atr5"] / (df["atr20"] + 1e-8)

        # Mansfield Relative Strength vs S&P 500 (SPY)
        aligned_spy = spy_close.reindex(df.index).ffill()
        base_ratio = close / (aligned_spy + 1e-8)
        sma_base = base_ratio.rolling(min(50, len(base_ratio))).mean()
        df["mansfield_rs"] = ((base_ratio / (sma_base + 1e-8)) - 1.0) * 100.0

        last = df.iloc[-1]
        prev = df.iloc[-2]

        curr_p = float(last["close"])
        curr_p_inr = curr_p * USD_TO_INR_APPROX
        chg_24h = ((curr_p - float(prev["close"])) / float(prev["close"])) * 100.0

        rvol = float(last["rvol"])
        vcp = float(last["vcp_ratio"])
        m_rs = float(last["mansfield_rs"])
        h20 = float(last["high20"]) if not np.isnan(last["high20"]) else curr_p
        h10 = float(last["high10"]) if not np.isnan(last["high10"]) else curr_p
        ema10 = float(last["ema10"])
        ema15 = float(last["ema15"])
        ema20 = float(last["ema20"])
        sma50 = float(last["sma50"]) if not np.isnan(last["sma50"]) else curr_p
        sma200 = float(last["sma200"]) if not np.isnan(last["sma200"]) else curr_p

        # ─── 4-PILLAR US QUANT SCORING (0 to 100) ───
        # Pillar 1: Trend & Moving Average Alignment (0-25 pts)
        p1_trend = 0.0
        if curr_p > ema20:
            p1_trend += 7.0
        if curr_p > sma50:
            p1_trend += 6.0
        if ema20 > sma50:
            p1_trend += 6.0
        if curr_spy_p > curr_spy_sma50:
            p1_trend += 6.0

        # Pillar 2: Mansfield Relative Strength vs S&P 500 (0-25 pts)
        p2_rs = 0.0
        if sym == "SPY":
            p2_rs = 18.0
        else:
            if m_rs > 0.0:
                p2_rs += 10.0
            if m_rs > 2.5:
                p2_rs += 8.0
            if m_rs > 6.0:
                p2_rs += 7.0

        # Pillar 3: Volume & Institutional Accumulation (0-25 pts)
        p3_vol = 0.0
        if rvol >= 1.15:
            p3_vol += 8.0
        if rvol >= 1.40:
            p3_vol += 9.0
        if rvol >= 1.80:
            p3_vol += 8.0

        # Pillar 4: Breakout & VCP Range Contraction (0-25 pts)
        p4_breakout = 0.0
        if curr_p >= h10 * 0.992:
            p4_breakout += 10.0
        if curr_p >= h20 * 0.990:
            p4_breakout += 10.0
        if vcp <= 0.72:
            p4_breakout += 5.0

        composite_score = round(p1_trend + p2_rs + p3_vol + p4_breakout, 1)
        if not entries_allowed:
            composite_score = min(composite_score, 45.0)

        # Setup & Verdict Determination
        is_breakout_20d = curr_p >= h20 * 0.990
        is_breakout_10d = curr_p >= h10 * 0.992
        is_rocket = (
            (is_breakout_20d or is_breakout_10d)
            and rvol >= 1.35
            and m_rs >= 2.0
            and u.get("tag") in ["mag7", "ai_semi", "growth"]
        )

        if not entries_allowed:
            verdict = "AVOID 🔴"
            action = "CASH PROTECT (MACRO BEAR)"
        elif composite_score >= 80.0 and is_rocket:
            verdict = "BUY 🟢"
            action = "🚀 HIGH-BETA ROCKET BREAKOUT"
        elif composite_score >= 70.0 and (is_breakout_20d or is_breakout_10d):
            verdict = "BUY 🟢"
            action = "BUY (STAGE 2 BREAKOUT)"
        elif composite_score >= 50.0 and curr_p > ema20:
            verdict = "HOLD 🟡"
            action = "HOLD / RIDE RUNNER"
        elif curr_p < ema20 * 0.96:
            verdict = "SELL 🔴"
            action = "SELL (TREND BROKEN)"
        else:
            verdict = "AVOID ⚪"
            action = "WAIT / CONSOLIDATION"

        # Trade Plan Levels (Optimized via 10-Year Tournament)
        stop_loss_usd = round(curr_p * 0.945, 2)  # -5.5% Hard Stop
        stop_loss_inr = round(stop_loss_usd * USD_TO_INR_APPROX, 2)
        target1_usd = round(curr_p * 1.18, 2)     # +18% Scale-out 35%
        target1_inr = round(target1_usd * USD_TO_INR_APPROX, 2)
        target2_usd = round(curr_p * 1.35, 2)     # +35% Monster Target
        target2_inr = round(target2_usd * USD_TO_INR_APPROX, 2)

        candidates.append({
            "symbol": sym,
            "display": u.get("display", sym),
            "name": u["name"],
            "sector": u["sector"],
            "tag": u.get("tag", "growth"),
            "price_usd": curr_p,
            "price_inr": curr_p_inr,
            "change_24h": round(chg_24h, 2),
            "score": composite_score,
            "verdict": verdict,
            "action": action,
            "trend_score": p1_trend,
            "rs_score": p2_rs,
            "vol_score": p3_vol,
            "breakout_score": p4_breakout,
            "rvol": round(rvol, 2),
            "vcp": round(vcp, 2),
            "mansfield_rs": round(m_rs, 2),
            "is_breakout": is_breakout_20d,
            "is_fast_breakout": is_breakout_10d,
            "is_rocket": is_rocket,
            "stop_loss_usd": stop_loss_usd,
            "stop_loss_inr": stop_loss_inr,
            "target1_usd": target1_usd,
            "target1_inr": target1_inr,
            "target2_usd": target2_usd,
            "target2_inr": target2_inr,
            "trailing_10ema_usd": round(ema10, 2),
            "trailing_10ema_inr": round(ema10 * USD_TO_INR_APPROX, 2),
            "trailing_15ema_usd": round(ema15, 2),
            "trailing_15ema_inr": round(ema15 * USD_TO_INR_APPROX, 2),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    return {
        "status": "OK",
        "macro": {
            "spy_price": curr_spy_p,
            "spy_sma50": curr_spy_sma50,
            "spy_pass": spy_pass,
            "qqq_price": curr_qqq_p,
            "qqq_sma50": curr_qqq_sma50,
            "qqq_pass": qqq_pass,
            "regime": macro_regime,
            "verdict": macro_verdict,
            "entries_allowed": entries_allowed,
        },
        "candidates": candidates,
    }


# ─── SHADOW TRACKING & PAPER TRADING EXECUTION ───────────────────

def execute_us_shadow_buy(
    symbol: str,
    candidate: dict,
    allocated_usd: float = 1500.0,
    strategy_mode: str = "Uncapped 10 EMA Trailing Runner",
) -> dict:
    """
    Execute simulated US paper buy order with fractional share support.
    Persists to SQLite paper_us_trades table.
    """
    conn = get_connection()
    try:
        open_trades = get_open_us_paper_trades(conn)
        if any(t["symbol"] == symbol for t in open_trades):
            return {"ok": False, "error": f"{symbol} is already an active open paper trade."}

        price_usd = candidate["price_usd"]
        if price_usd <= 0:
            return {"ok": False, "error": f"Invalid price for {symbol}."}

        # Statutory deduction model (SEC + FINRA TAF)
        shares = round(allocated_usd / price_usd, 4)
        sec_fee = allocated_usd * 0.0000278
        finra_taf = shares * 0.000166
        tot_fee_usd = round(sec_fee + finra_taf, 4)

        trade = {
            "symbol": symbol,
            "name": candidate.get("name", symbol),
            "sector": candidate.get("sector", "US Equities"),
            "entry_price_usd": price_usd,
            "shares": shares,
            "allocated_usd": allocated_usd,
            "allocated_inr": round(allocated_usd * USD_TO_INR_APPROX, 2),
            "stop_loss_usd": candidate["stop_loss_usd"],
            "target_price_usd": candidate["target1_usd"],
            "trailing_ema_usd": candidate["trailing_10ema_usd"],
            "notes": f"Score: {candidate['score']} | {candidate['action']} | Fee: ${tot_fee_usd:.4f}",
        }
        trade_id = create_paper_us_trade(conn, trade)
        return {
            "ok": True,
            "trade_id": trade_id,
            "symbol": symbol,
            "shares": shares,
            "allocated_usd": allocated_usd,
        }
    finally:
        conn.close()


def sync_us_paper_trades(data: dict[str, pd.DataFrame]) -> dict:
    """
    Synchronize open US paper trades with latest daily price bars.
    Checks automated exit triggers:
    1. Hard Stop Hit (-5.5%)
    2. 10 EMA Trailing Exit (when in profit)
    3. Target 1 (+18%) scale-out
    Returns live floating MTM P&L in USD and INR.
    """
    conn = get_connection()
    try:
        open_trades = get_open_us_paper_trades(conn)
        closed_trades = get_closed_us_paper_trades(conn, limit=100)

        processed_open = []
        auto_exits = []

        for t in open_trades:
            sym = t["symbol"]
            if sym not in data:
                processed_open.append(t)
                continue

            df = data[sym]
            last = df.iloc[-1]
            curr_p_usd = float(last["close"])
            low_p_usd = float(last["low"])
            high_p_usd = float(last["high"])
            curr_p_inr = curr_p_usd * USD_TO_INR_APPROX

            current_val_usd = t["shares"] * curr_p_usd
            current_val_inr = current_val_usd * USD_TO_INR_APPROX
            unrealized_pnl_usd = current_val_usd - t["allocated_usd"]
            unrealized_pnl_inr = unrealized_pnl_usd * USD_TO_INR_APPROX
            unrealized_pnl_pct = (unrealized_pnl_usd / (t["allocated_usd"] + 1e-8)) * 100.0

            exit_reason = None
            exit_px_usd = 0.0

            # 1. Hard Stop Hit
            if low_p_usd <= t["stop_loss_usd"]:
                exit_reason = "HARD STOP-LOSS (-5.5%)"
                exit_px_usd = t["stop_loss_usd"]
            # 2. 10 EMA Trailing Exit
            elif unrealized_pnl_pct >= 4.0 and curr_p_usd < t.get("trailing_ema_usd", 0.0):
                exit_reason = "10 EMA TRAILING EXIT"
                exit_px_usd = curr_p_usd
            # 3. Dynamic trail upward
            else:
                new_trail = float(last.get("ema10", t.get("trailing_ema_usd", 0.0)))
                new_stop = max(t["stop_loss_usd"], curr_p_usd * 0.945)
                update_us_paper_trade_stop(conn, t["id"], new_stop, new_trail)

            if exit_reason:
                final_val_usd = t["shares"] * exit_px_usd
                fee_usd = (final_val_usd * 0.0000278) + (t["shares"] * 0.000166)
                net_val_usd = final_val_usd - fee_usd
                realized_pnl_usd = net_val_usd - t["allocated_usd"]
                realized_pnl_inr = realized_pnl_usd * USD_TO_INR_APPROX
                realized_pnl_pct = (realized_pnl_usd / (t["allocated_usd"] + 1e-8)) * 100.0

                close_paper_us_trade(
                    conn,
                    trade_id=t["id"],
                    exit_price_usd=exit_px_usd,
                    exit_reason=exit_reason,
                    pnl_usd=realized_pnl_usd,
                    pnl_inr=realized_pnl_inr,
                    pnl_pct=realized_pnl_pct,
                )
                auto_exits.append({
                    "symbol": sym,
                    "reason": exit_reason,
                    "pnl_usd": realized_pnl_usd,
                    "pnl_inr": realized_pnl_inr,
                    "pnl_pct": realized_pnl_pct,
                })
            else:
                dist_to_stop = ((curr_p_usd - t["stop_loss_usd"]) / curr_p_usd) * 100.0
                t_copy = dict(t)
                t_copy.update({
                    "current_price_usd": curr_p_usd,
                    "current_price_inr": curr_p_inr,
                    "current_val_usd": current_val_usd,
                    "current_val_inr": current_val_inr,
                    "unrealized_pnl_usd": unrealized_pnl_usd,
                    "unrealized_pnl_inr": unrealized_pnl_inr,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "dist_to_stop_pct": dist_to_stop,
                })
                processed_open.append(t_copy)

        if auto_exits:
            closed_trades = get_closed_us_paper_trades(conn, limit=100)

        tot_allocated_usd = sum(t["allocated_usd"] for t in processed_open)
        tot_allocated_inr = tot_allocated_usd * USD_TO_INR_APPROX
        tot_floating_pnl_usd = sum(t.get("unrealized_pnl_usd", 0.0) for t in processed_open)
        tot_floating_pnl_inr = tot_floating_pnl_usd * USD_TO_INR_APPROX
        tot_realized_pnl_usd = sum(t.get("pnl_usd", 0.0) for t in closed_trades)
        tot_realized_pnl_inr = tot_realized_pnl_usd * USD_TO_INR_APPROX

        wins = [t for t in closed_trades if t.get("pnl_usd", 0.0) > 0]
        losses = [t for t in closed_trades if t.get("pnl_usd", 0.0) <= 0]
        win_rate = (len(wins) / len(closed_trades) * 100.0) if closed_trades else 0.0
        gross_win = sum(t.get("pnl_usd", 0.0) for t in wins)
        gross_loss = abs(sum(t.get("pnl_usd", 0.0) for t in losses))
        profit_factor = (gross_win / (gross_loss + 1e-8)) if gross_loss > 0 else (gross_win if gross_win > 0 else 1.0)

        return {
            "open_trades": processed_open,
            "closed_trades": closed_trades,
            "auto_exits": auto_exits,
            "tot_allocated_usd": round(tot_allocated_usd, 2),
            "tot_allocated_inr": round(tot_allocated_inr, 2),
            "tot_floating_pnl_usd": round(tot_floating_pnl_usd, 2),
            "tot_floating_pnl_inr": round(tot_floating_pnl_inr, 2),
            "tot_realized_pnl_usd": round(tot_realized_pnl_usd, 2),
            "tot_realized_pnl_inr": round(tot_realized_pnl_inr, 2),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "total_closed_count": len(closed_trades),
        }
    finally:
        conn.close()


def manual_close_us_paper_trade(trade_id: int, exit_price_usd: float, exit_reason: str = "MANUAL EXIT") -> dict:
    """Manually exit an open US paper trade at the specified price."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM paper_us_trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "error": f"Trade ID {trade_id} not found."}
        t = dict(row)
        if t["status"] != "OPEN":
            return {"ok": False, "error": f"Trade ID {trade_id} is already closed."}

        final_val_usd = t["shares"] * exit_price_usd
        fee_usd = (final_val_usd * 0.0000278) + (t["shares"] * 0.000166)
        net_val_usd = final_val_usd - fee_usd
        realized_pnl_usd = net_val_usd - t["allocated_usd"]
        realized_pnl_inr = realized_pnl_usd * USD_TO_INR_APPROX
        realized_pnl_pct = (realized_pnl_usd / (t["allocated_usd"] + 1e-8)) * 100.0

        close_paper_us_trade(
            conn,
            trade_id=trade_id,
            exit_price_usd=exit_price_usd,
            exit_reason=exit_reason,
            pnl_usd=realized_pnl_usd,
            pnl_inr=realized_pnl_inr,
            pnl_pct=realized_pnl_pct,
        )
        return {
            "ok": True,
            "trade_id": trade_id,
            "pnl_usd": round(realized_pnl_usd, 2),
            "pnl_inr": round(realized_pnl_inr, 2),
            "pnl_pct": round(realized_pnl_pct, 2),
        }
    finally:
        conn.close()
