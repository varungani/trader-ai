"""
TraderAI - Fundamental Analysis Engine
Evaluates company financials and generates a FundamentalScore (0-100).
"""
import logging

logger = logging.getLogger(__name__)


def compute_fundamental_score(stock_info: dict) -> dict:
    """
    Compute a fundamental analysis score based on financial ratios.
    
    Args:
        stock_info: Dict from market_data.fetch_stock_info()
    
    Returns:
        Dict with overall score (0-100), breakdown, and key observations
    """
    ticker = stock_info.get("symbol", "")
    scores = []
    observations = []

    try:
        # ─── VALUATION ───────────────────────────────────────
        # P/E Ratio (lower is generally better, but context matters)
        pe = stock_info.get("pe_ratio")
        if pe is not None and pe > 0:
            if pe < 15:
                pe_score = 85
                observations.append(f"Low P/E ({pe:.1f}) — potentially undervalued")
            elif pe < 25:
                pe_score = 65
                observations.append(f"Moderate P/E ({pe:.1f}) — fairly valued")
            elif pe < 40:
                pe_score = 45
                observations.append(f"High P/E ({pe:.1f}) — priced for growth")
            else:
                pe_score = 25
                observations.append(f"Very high P/E ({pe:.1f}) — expensive")
        else:
            pe_score = 40  # No data or negative earnings
            observations.append("P/E not available or negative earnings")

        scores.append(("P/E Ratio", pe_score, 0.15))

        # PEG Ratio (P/E adjusted for growth; < 1 is ideal)
        peg = stock_info.get("peg_ratio")
        if peg is not None and peg > 0:
            if peg < 1:
                peg_score = 85
                observations.append(f"PEG {peg:.2f} — undervalued relative to growth")
            elif peg < 1.5:
                peg_score = 65
            elif peg < 2.5:
                peg_score = 45
            else:
                peg_score = 25
        else:
            peg_score = 50

        scores.append(("PEG Ratio", peg_score, 0.10))

        # Price to Book
        pb = stock_info.get("price_to_book")
        if pb is not None and pb > 0:
            if pb < 2:
                pb_score = 75
            elif pb < 5:
                pb_score = 55
            else:
                pb_score = 35
        else:
            pb_score = 50

        scores.append(("Price/Book", pb_score, 0.08))

        # ─── PROFITABILITY ───────────────────────────────────
        # Return on Equity
        roe = stock_info.get("roe")
        if roe is not None:
            roe_pct = roe * 100 if abs(roe) < 1 else roe
            if roe_pct > 20:
                roe_score = 85
                observations.append(f"Strong ROE ({roe_pct:.1f}%) — efficient capital use")
            elif roe_pct > 12:
                roe_score = 65
            elif roe_pct > 5:
                roe_score = 45
            else:
                roe_score = 25
                observations.append(f"Weak ROE ({roe_pct:.1f}%)")
        else:
            roe_score = 50

        scores.append(("ROE", roe_score, 0.15))

        # ─── FINANCIAL HEALTH ────────────────────────────────
        # Debt-to-Equity (Sector-Adjusted: Banks/NBFCs operate on deposits/debt as inventory)
        sector_str = (stock_info.get("sector") or "").lower()
        industry_str = (stock_info.get("industry") or "").lower()
        is_financial = any(w in sector_str or w in industry_str for w in ("bank", "financial", "finance", "nbfc"))

        de = stock_info.get("debt_to_equity")
        if is_financial:
            de_score = 75  # Neutral-healthy default; banking solvency is governed by CAR/NPA, not industrial D/E
            observations.append("Financials/Banking sector — D/E normalized (deposits are operational capital)")
        elif de is not None:
            if de < 50:
                de_score = 85
                observations.append(f"Low debt (D/E: {de:.0f}%) — financially strong")
            elif de < 100:
                de_score = 65
            elif de < 200:
                de_score = 40
            else:
                de_score = 20
                observations.append(f"High debt (D/E: {de:.0f}%) — risky")
        else:
            de_score = 50

        scores.append(("Debt/Equity", de_score, 0.12))

        # ─── GROWTH ──────────────────────────────────────────
        # Revenue Growth
        rev_growth = stock_info.get("revenue_growth")
        if rev_growth is not None:
            rev_pct = rev_growth * 100 if abs(rev_growth) < 5 else rev_growth
            if rev_pct > 20:
                rev_score = 85
                observations.append(f"Strong revenue growth ({rev_pct:.1f}%)")
            elif rev_pct > 10:
                rev_score = 70
            elif rev_pct > 0:
                rev_score = 50
            else:
                rev_score = 25
                observations.append(f"Revenue declining ({rev_pct:.1f}%)")
        else:
            rev_score = 50

        scores.append(("Revenue Growth", rev_score, 0.15))

        # Earnings Growth
        earn_growth = stock_info.get("earnings_growth")
        if earn_growth is not None:
            earn_pct = earn_growth * 100 if abs(earn_growth) < 5 else earn_growth
            if earn_pct > 25:
                earn_score = 85
            elif earn_pct > 10:
                earn_score = 70
            elif earn_pct > 0:
                earn_score = 50
            else:
                earn_score = 25
        else:
            earn_score = 50

        scores.append(("Earnings Growth", earn_score, 0.15))

        # ─── DIVIDEND ────────────────────────────────────────
        div_yield = stock_info.get("dividend_yield")
        if div_yield is not None and div_yield > 0:
            div_pct = div_yield * 100 if div_yield < 1 else div_yield
            if div_pct > 3:
                div_score = 75
                observations.append(f"Good dividend yield ({div_pct:.2f}%)")
            elif div_pct > 1:
                div_score = 60
            else:
                div_score = 50
        else:
            div_score = 45  # No dividend isn't bad for growth stocks

        scores.append(("Dividend", div_score, 0.05))

        # ─── 52-WEEK RANGE POSITION ──────────────────────────
        price = stock_info.get("current_price", 0)
        high_52 = stock_info.get("fifty_two_week_high")
        low_52 = stock_info.get("fifty_two_week_low")

        if price and high_52 and low_52 and high_52 > low_52:
            position = (price - low_52) / (high_52 - low_52)
            if position < 0.3:
                range_score = 70  # Near 52-week low — potential value
                observations.append(f"Trading near 52-week low ({position:.0%} of range)")
            elif position > 0.9:
                range_score = 35  # Near 52-week high — less upside
                observations.append(f"Near 52-week high ({position:.0%} of range)")
            else:
                range_score = 55
        else:
            range_score = 50

        scores.append(("52-Week Range", range_score, 0.05))

        # ─── FINAL SCORE ─────────────────────────────────────
        weighted_score = sum(score * weight for _, score, weight in scores)
        total_weight = sum(weight for _, _, weight in scores)
        final_score = weighted_score / total_weight if total_weight > 0 else 50

        # Determine signal
        if final_score >= 70:
            signal = "STRONG_BUY"
        elif final_score >= 60:
            signal = "BUY"
        elif final_score >= 45:
            signal = "HOLD"
        elif final_score >= 35:
            signal = "SELL"
        else:
            signal = "STRONG_SELL"

        return {
            "ticker": ticker,
            "score": round(final_score, 1),
            "signal": signal,
            "breakdown": {name: round(score, 1) for name, score, _ in scores},
            "observations": observations,
            "raw_data": {
                "pe_ratio": pe,
                "peg_ratio": peg,
                "roe": roe,
                "debt_to_equity": de,
                "revenue_growth": rev_growth,
                "earnings_growth": earn_growth,
                "dividend_yield": div_yield,
                "market_cap": stock_info.get("market_cap", 0),
            },
        }

    except Exception as e:
        logger.error(f"Error computing fundamental score for {ticker}: {e}")
        return {"ticker": ticker, "score": 50, "signal": "NEUTRAL", "error": str(e)}
