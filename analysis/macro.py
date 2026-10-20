"""
TraderAI - Macro & Geopolitical Analysis Engine
Evaluates broader market conditions, policy, and sector trends.
"""
import pandas as pd
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.market_data import fetch_index_data, fetch_commodity_data
from config import INDICES

logger = logging.getLogger(__name__)


def compute_macro_score() -> dict:
    """
    Compute a macro/market-conditions score based on index trends,
    commodity prices, and market breadth.
    
    Returns:
        Dict with macro score (0-100), market regime, and observations
    """
    scores = []
    observations = []
    market_data = {}

    try:
        # ─── NIFTY 50 TREND ─────────────────────────────────
        nifty = fetch_index_data(INDICES["nifty50"], period="6mo")
        if not nifty.empty and len(nifty) >= 50:
            close = nifty["Close"]
            sma_50 = close.rolling(50).mean()

            # Market above/below 50 SMA
            is_above_50 = bool(close.iloc[-1] > sma_50.iloc[-1])
            market_data["nifty_above_50_sma"] = is_above_50
            if is_above_50:
                nifty_score = 65
                trend = "UPTREND"
            else:
                nifty_score = 35
                trend = "DOWNTREND"

            # 1-month return
            ret_1m = (close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) >= 22 else 0
            nifty_score += ret_1m * 2  # Adjust based on momentum

            observations.append(f"NIFTY50 in {trend} (1M return: {ret_1m:.1f}%)")
            market_data["nifty50_return_1m"] = round(ret_1m, 2)
            scores.append(("Market Trend", max(0, min(100, nifty_score)), 0.30))

        # ─── VOLATILITY (VIX proxy via NIFTY range) ──────────
        if not nifty.empty and len(nifty) >= 20:
            daily_returns = nifty["Close"].pct_change().tail(20)
            volatility = daily_returns.std() * (252 ** 0.5) * 100  # Annualized

            if volatility < 12:
                vol_score = 75  # Low vol — favorable for stocks
                observations.append(f"Low market volatility ({volatility:.1f}%) — calm market")
            elif volatility < 20:
                vol_score = 55
                observations.append(f"Moderate volatility ({volatility:.1f}%)")
            else:
                vol_score = 30
                observations.append(f"High volatility ({volatility:.1f}%) — risky market")

            market_data["market_volatility"] = round(volatility, 2)
            scores.append(("Volatility", vol_score, 0.20))

        # ─── SECTOR ROTATION SIGNALS ─────────────────────────
        # Compare sector performances to identify rotation
        sector_perfs = {}
        sector_indices = {
            "nifty_bank": INDICES.get("nifty_bank", "^NSEBANK"),
            "nifty_it": INDICES.get("nifty_it", "^CNXIT"),
        }

        for name, symbol in sector_indices.items():
            idx_data = fetch_index_data(symbol, period="3mo")
            if not idx_data.empty and len(idx_data) >= 22:
                ret = (idx_data["Close"].iloc[-1] / idx_data["Close"].iloc[-22] - 1) * 100
                sector_perfs[name] = round(ret, 2)

        if sector_perfs:
            best_sector = max(sector_perfs, key=sector_perfs.get)
            worst_sector = min(sector_perfs, key=sector_perfs.get)
            observations.append(
                f"Sector rotation: {best_sector} leading ({sector_perfs[best_sector]:+.1f}%), "
                f"{worst_sector} lagging ({sector_perfs[worst_sector]:+.1f}%)"
            )
            market_data["sector_performance"] = sector_perfs

        # ─── COMMODITY SIGNALS ───────────────────────────────
        # Gold often moves inverse to equity risk appetite
        gold = fetch_commodity_data("GC=F", period="3mo")
        if not gold.empty and len(gold) >= 22:
            gold_ret = (gold["Close"].iloc[-1] / gold["Close"].iloc[-22] - 1) * 100
            if gold_ret > 5:
                commodity_score = 35  # Gold rallying = risk-off
                observations.append(f"Gold rallying ({gold_ret:.1f}%) — risk-off signal")
            elif gold_ret < -3:
                commodity_score = 65  # Gold falling = risk-on
            else:
                commodity_score = 50

            market_data["gold_return_1m"] = round(gold_ret, 2)
            scores.append(("Commodity Signal", commodity_score, 0.15))

        # Crude Oil — high oil hurts Indian stocks (India imports oil)
        crude = fetch_commodity_data("CL=F", period="3mo")
        if not crude.empty and len(crude) >= 22:
            crude_ret = (crude["Close"].iloc[-1] / crude["Close"].iloc[-22] - 1) * 100
            if crude_ret > 10:
                crude_score = 30  # High oil = bad for India
                observations.append(f"Crude oil surging ({crude_ret:.1f}%) — negative for Indian markets")
            elif crude_ret < -5:
                crude_score = 70
                observations.append(f"Crude down ({crude_ret:.1f}%) — positive for India")
            else:
                crude_score = 50

            market_data["crude_return_1m"] = round(crude_ret, 2)
            scores.append(("Crude Oil Impact", crude_score, 0.15))

        # ─── FII / DII INSTITUTIONAL FLOWS ───────────────────
        try:
            from data.news_oss import fetch_google_news
            fii_articles = fetch_google_news("FII DII net buy sell India stock market", max_articles=5)
            fii_buy = sum(1 for a in fii_articles if any(k in (a.get("headline", "") + a.get("summary", "")).lower() for k in ("fii buy", "fpi buy", "inflow", "buying")))
            fii_sell = sum(1 for a in fii_articles if any(k in (a.get("headline", "") + a.get("summary", "")).lower() for k in ("fii sell", "fpi sell", "outflow", "selling")))
            if fii_buy > fii_sell:
                fii_score = 65
                observations.append("FII/Institutional net flows positive (buying bias)")
            elif fii_sell > fii_buy:
                fii_score = 35
                observations.append("FII/Institutional net outflows detected (caution)")
            else:
                fii_score = 50
            scores.append(("Institutional Flows", fii_score, 0.15))
        except Exception:
            pass

        # ─── FINAL SCORE ─────────────────────────────────────
        if scores:
            weighted = sum(s * w for _, s, w in scores)
            total_w = sum(w for _, _, w in scores)
            final_score = weighted / total_w
        else:
            final_score = 50

        # Market regime
        if final_score >= 65:
            regime = "BULLISH"
        elif final_score >= 45:
            regime = "NEUTRAL"
        else:
            regime = "BEARISH"

        # Market Regime Gate: Hard entry gate on new swing positions
        nifty_above_50 = market_data.get("nifty_above_50_sma", True)
        market_vol = market_data.get("market_volatility", 15.0)

        regime_gate_cleared = True
        gate_reasons = []

        if not nifty_above_50:
            regime_gate_cleared = False
            gate_reasons.append("NIFTY 50 is trading below its 50-day SMA (macro downtrend)")
        if market_vol > 24.0:
            regime_gate_cleared = False
            gate_reasons.append(f"Market volatility is elevated at {market_vol:.1f}% (> 24.0% risk threshold)")

        regime_gate_status = "CLEAR" if regime_gate_cleared else "CASH_PRESERVATION"
        regime_gate_reason = " & ".join(gate_reasons) if gate_reasons else "NIFTY 50 is above 50 SMA and volatility is normal. Clear for new swing entries."

        return {
            "score": round(final_score, 1),
            "regime": regime,
            "observations": observations,
            "breakdown": {name: round(s, 1) for name, s, _ in scores},
            "market_data": market_data,
            "is_regime_gate_cleared": regime_gate_cleared,
            "regime_gate_status": regime_gate_status,
            "regime_gate_reason": regime_gate_reason,
            "no_trade_today": not regime_gate_cleared,
        }

    except Exception as e:
        logger.error(f"Error computing macro score: {e}")
        return {
            "score": 50,
            "regime": "NEUTRAL",
            "observations": [f"Error: {e}"],
            "market_data": {},
            "is_regime_gate_cleared": True,
            "regime_gate_status": "CLEAR",
            "regime_gate_reason": "Default neutral fallback",
            "no_trade_today": False,
        }


def get_macro_context_for_llm() -> str:
    """
    Generate a text summary of macro conditions for the LLM.
    
    Returns:
        Human-readable summary string
    """
    macro = compute_macro_score()
    
    lines = [f"Market Regime: {macro['regime']} (Score: {macro['score']}/100)"]
    for obs in macro.get("observations", []):
        lines.append(f"- {obs}")
    
    return "\n".join(lines)
