"""
TraderAI - Buy / Hold / Sell recommender
Pure rules on multi-factor scores + portfolio risk constraints.
Never places orders — recommendations only.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_CONFIG, TICKER_TO_SECTOR

logger = logging.getLogger(__name__)


def decide_action(score_result: dict, holding: Optional[dict] = None) -> dict:
    """
    Map final_score (+ event overrides) to BUY / HOLD / SELL / STRONG_BUY / STRONG_SELL.
    If holding is provided, bias toward portfolio actions (trim / add / exit).
    """
    final = float(score_result.get("final_score", 50))
    event_signal = (score_result.get("event_risk") or {}).get("signal", "NEUTRAL")
    event_score = float(score_result.get("event_risk_score", 50))
    risk = score_result.get("risk_level", "MEDIUM")

    buy_min = RISK_CONFIG["min_score_to_buy"]
    sell_max = RISK_CONFIG["max_score_to_sell"]
    setup_pattern = "NONE"
    vcp_ratio = 1.0

    # Hard risk override
    if event_signal == "HIGH_RISK" or event_score < 28:
        action = "SELL" if holding else "AVOID"
        confidence = "HIGH"
        rationale = "Severe event risk (sanctions / fraud / insolvency / regulatory)."
    elif final >= buy_min:
        # ─── Fortress Shortlisting Gates (Targeting >= 75-80% Win Rate) ─────
        sector_rs = score_result.get("sector_relative_strength") or {}
        sector_status = sector_rs.get("status", "NEUTRAL")
        sector_rs_pct = float(sector_rs.get("relative_strength_pct") or 0.0)
        sector_name = sector_rs.get("sector", "General")
        
        tech_indicators = (score_result.get("technical") or {}).get("indicators") or {}
        ema_info = tech_indicators.get("ema_20") or {}
        dev_pct = float(ema_info.get("deviation_pct") or 0.0)
        sma_info = tech_indicators.get("sma_crossover") or {}
        vol_info = tech_indicators.get("volume") or {}
        vol_ratio = float(vol_info.get("volume_ratio") or 1.0)
        vcp_info = tech_indicators.get("vcp") or {}
        vcp_ratio = float(vcp_info.get("vcp_ratio") or 1.0)
        sweet_info = tech_indicators.get("sweet_spot_rebound") or {}
        is_sweet_spot = bool(sweet_info.get("is_sweet_spot"))

        # Determine Winning Pattern
        setup_pattern = "NONE"
        if vcp_info.get("is_contracted") and vol_ratio >= 1.2:
            setup_pattern = "VCP_BREAKOUT"
        elif is_sweet_spot:
            setup_pattern = "20EMA_SWEET_SPOT"

        if not holding:
            # Gate 1: Strict Zero-Tolerance on Sector Drag
            if sector_status in ("LAGGING", "SEVERE_DRAG"):
                action = "HOLD"
                confidence = "LOW"
                rationale = f"SECTOR_DRAG: Sector {sector_name} is lagging Nifty ({sector_rs_pct:+.2f}% RS). Buying into an underperforming sector has a >65% failure rate; candidate gated to HOLD."
            
            # Gate 2: Minervini Stage 2 Trend Template (Must be above long-term moving averages)
            elif sma_info.get("signal") == "BEARISH":
                action = "HOLD"
                confidence = "LOW"
                rationale = "NOT_STAGE_2: Stock is below major moving averages (50 SMA < 200 SMA / Stage 3-4 distribution). Prohibits buying against long-term trend."

            # Gate 3: Sweet-Spot Entry Corridor (Must be within -2.5% to +6.0% of 20 EMA)
            elif dev_pct > 6.0:
                action = "HOLD"
                confidence = "LOW"
                rationale = f"WAIT_FOR_PULLBACK: Stock is +{dev_pct:.1f}% stretched above its 20 EMA (over-extended > 6.0%). High risk of intraday mean-reversion. Wait for consolidation retest near support."
            elif dev_pct < -2.5:
                action = "HOLD"
                confidence = "LOW"
                rationale = f"BREAKDOWN_BELOW_EMA: Stock is -{abs(dev_pct):.1f}% below dynamic 20 EMA support line."

            # Gate 4: Institutional Volume Confirmation (Must not be dry volume)
            elif vol_ratio < 1.05 and final < 78:
                action = "HOLD"
                confidence = "LOW"
                rationale = f"LOW_INSTITUTIONAL_VOLUME: Volume ratio is only {vol_ratio:.2f}x (< 1.05x 20-day average). Lacks institutional accumulation; high risk of fakeout."

            else:
                action = "STRONG_BUY" if final >= 78 else "BUY"
                confidence = "HIGH" if final >= 75 else "MEDIUM"
                pattern_prefix = f"[{setup_pattern}] " if setup_pattern != "NONE" else ""
                rationale = f"{pattern_prefix}High-Conviction Fortress BUY: Multi-factor score ({final:.1f}) cleared all 5 institutional edge gates (Stage 2 trend, sector tailwind {sector_name} {sector_rs_pct:+.1f}%, volume expansion)."
        else:
            action = "STRONG_BUY" if final >= 78 else "BUY"
            confidence = "HIGH" if final >= 75 else "MEDIUM"
            pattern_prefix = f"[{setup_pattern}] " if setup_pattern != "NONE" else ""
            rationale = f"{pattern_prefix}High-conviction multi-factor score clears buy threshold."
    elif final <= sell_max - 10:
        action = "STRONG_SELL"
        confidence = "HIGH"
        rationale = "Multi-factor score deeply below sell threshold."
    elif final <= sell_max:
        action = "SELL"
        confidence = "MEDIUM"
        rationale = "Score below sell threshold."
    else:
        action = "HOLD"
        confidence = "MEDIUM"
        rationale = "Score inside hold band — no edge."

    # Portfolio-aware adjustments
    portfolio_note = ""
    if holding:
        pnl_pct = holding.get("pnl_percent")
        if pnl_pct is None:
            avg_px = float(holding.get("avg_price") or 0)
            cur_px = float(holding.get("current_price") or avg_px)
            pnl_pct = ((cur_px - avg_px) / avg_px * 100) if avg_px > 0 else 0.0
        else:
            pnl_pct = float(pnl_pct)
        qty = int(holding.get("quantity") or 0)
        if pnl_pct <= -6.0:
            action = "SELL"
            confidence = "HIGH"
            rationale = "System stop-loss trigger reached (-6.0%)."
            portfolio_note = f"Stop-loss breached ({pnl_pct:.1f}% <= -6.0%); exit holding immediately to protect capital."
        elif action in ("BUY", "STRONG_BUY") and pnl_pct < -5.0 and final < buy_min + 5:
            action = "HOLD"
            portfolio_note = "Position in drawdown; anti-averaging rule blocks adding until reversal confirms."
        elif action == "HOLD" and pnl_pct > 25 and final < 55:
            action = "TRIM"
            portfolio_note = "Large unrealized gain with weakening score — consider booking partial profits."
        elif action in ("SELL", "STRONG_SELL") and qty > 0:
            portfolio_note = "Exit or reduce existing holding to cut risk."
        elif action in ("BUY", "STRONG_BUY"):
            portfolio_note = "May add to existing position within risk caps."
        elif action == "HOLD" and not portfolio_note:
            portfolio_note = "Position intact within acceptable risk bands; maintain holding."

    return {
        "action": action,
        "confidence": confidence,
        "rationale": rationale,
        "portfolio_note": portfolio_note,
        "final_score": final,
        "is_held": holding is not None,
        "setup_pattern": setup_pattern,
        "vcp_ratio": round(vcp_ratio, 2),
    }


def apply_portfolio_risk_gates(
    recommendation: dict,
    score_result: dict,
    portfolio_summary: Optional[dict] = None,
) -> dict:
    """
    Downgrade BUY if position/sector concentration would breach RISK_CONFIG,
    or if liquidity / macro regime gates fail.
    """
    out = dict(recommendation)
    warnings = list(out.get("warnings") or [])

    if recommendation["action"] not in ("BUY", "STRONG_BUY"):
        out["warnings"] = warnings
        return out

    # 1. Liquidity Gate (ADTV >= ₹5 Crore minimum turnover)
    tech_ind = (score_result.get("technical") or {}).get("indicators", {})
    adtv_info = tech_ind.get("adtv", {})
    if adtv_info and not adtv_info.get("is_liquid", True):
        warnings.append(f"Low liquidity: ADTV is ₹{adtv_info.get('adtv_crores', 0):.1f} Cr (< ₹5 Cr safety threshold) — risk of circuit freeze.")
        out["action"] = "HOLD"
        out["rationale"] = "Blocked by Liquidity Gate (ADTV < ₹5 Cr)."

    # 2. Hard Macro Regime Gate (Nifty Trend / Volatility Gate with Sector Decoupling)
    macro_info = score_result.get("macro") or {}
    sector_info = score_result.get("sector_relative_strength") or {}
    sec_status = sector_info.get("status", "NEUTRAL")
    sec_rs = float(sector_info.get("relative_strength_pct") or 0.0)
    final_score = float(score_result.get("final_score") or 0.0)

    # Sector Decoupling: Leaders in non-lagging sectors with score >= 65 are exempt from blanket beta shutdown
    is_sector_decoupled = bool(
        final_score >= 65.0 
        and sec_status not in ("LAGGING", "SEVERE_DRAG")
    )

    if not macro_info.get("is_regime_gate_cleared", True) or macro_info.get("no_trade_today"):
        gate_msg = macro_info.get("regime_gate_reason", "Market in adverse regime")
        if is_sector_decoupled:
            warnings.append(f"Hard Market Regime Gate: {gate_msg} — Sector Decoupling Active for {sector_info.get('sector', 'Leader')} ({sec_rs:+.1f}% RS vs Nifty).")
            out["is_sector_decoupled"] = True
            out["regime_context"] = f"SECTOR_ALPHA_DECOUPLED ({sec_rs:+.1f}% RS)"
        else:
            warnings.append(f"Hard Market Regime Gate: {gate_msg} — Cash preservation active; new BUYs prohibited.")
            out["action"] = "HOLD"
            out["rationale"] = f"Blocked by Hard Market Regime Gate ({macro_info.get('regime_gate_status', 'CASH_PRESERVATION')})."
    else:
        regime = str(macro_info.get("regime") or "").upper()
        if any(k in regime for k in ("VOLATIL", "DOWNTREND", "BEAR", "CORRECTION")):
            if is_sector_decoupled:
                warnings.append(f"Market in '{regime}' — Sector Decoupling Active ({sec_rs:+.1f}% RS).")
                out["is_sector_decoupled"] = True
                out["regime_context"] = f"SECTOR_ALPHA_DECOUPLED ({sec_rs:+.1f}% RS)"
            else:
                warnings.append(f"Hard Macro Regime Gate: Market is in '{regime}' — Fresh BUYs strictly prohibited to preserve cash (100% Cash Preservation; zero exceptions).")
                out["action"] = "HOLD"
                out["rationale"] = f"Blocked by Hard Macro Regime Gate ({regime}): Capital preservation active during market drawdown."

    if portfolio_summary:
        holdings = portfolio_summary.get("holdings") or []
        total = float(portfolio_summary.get("total_current_value") or 0)
        ticker = score_result.get("ticker")
        sector = score_result.get("sector") or TICKER_TO_SECTOR.get(ticker, "")

        if total > 0 and holdings:
            # Existing weight of this ticker
            existing = next((h for h in holdings if h.get("symbol") == ticker), None)
            if existing:
                px = float(existing.get("current_price") or existing.get("avg_price") or 0)
                qty = float(existing.get("quantity") or 0)
                weight = (px * qty) / total
                if weight >= RISK_CONFIG["max_position_pct"]:
                    warnings.append(
                        f"Position already ≥{RISK_CONFIG['max_position_pct']*100:.0f}% — do not add."
                    )
                    out["action"] = "HOLD"
                    out["rationale"] = "Blocked by max position size rule."

            sector_w = (portfolio_summary.get("sector_weights") or {}).get(sector, 0) / 100
            if sector_w >= RISK_CONFIG["max_sector_pct"]:
                warnings.append(
                    f"Sector {sector} already ≥{RISK_CONFIG['max_sector_pct']*100:.0f}% — avoid adding."
                )
                if out["action"] in ("BUY", "STRONG_BUY"):
                    out["action"] = "HOLD"
                    out["rationale"] = "Blocked by max sector concentration rule."

        if len(holdings) >= RISK_CONFIG["max_open_positions"] and not any(
            h.get("symbol") == ticker for h in holdings
        ):
            warnings.append("Max open positions reached.")
            out["action"] = "HOLD"
            out["rationale"] = "Blocked by max open positions rule."

    out["warnings"] = warnings
    return out


from engine.trade_policy import calculate_trade_levels


def build_recommendation(
    score_result: dict,
    holding: Optional[dict] = None,
    portfolio_summary: Optional[dict] = None,
) -> dict:
    """Full recommendation payload for UI / DB using Unified Trade Policy."""
    decision = decide_action(score_result, holding=holding)
    decision = apply_portfolio_risk_gates(decision, score_result, portfolio_summary)

    # Single source of truth trade levels calculation
    cur_px = float(score_result.get("current_price") or 0.0)
    tech = score_result.get("technical") or {}
    atr_val = float(tech.get("atr") or 0.0) if tech.get("atr") else None
    tf = score_result.get("preferred_timeframe") or score_result.get("timeframe", "short_term")
    is_runner = bool(float(score_result.get("final_score") or 50) >= 68 and float(score_result.get("event_risk_score") or 50) >= 55)
    levels = calculate_trade_levels(cur_px, atr=atr_val, timeframe=tf, is_monster_runner=is_runner)

    stop_px = levels.stop_loss if levels.stop_loss > 0 else float(score_result.get("stop_loss") or (cur_px * 0.94))
    target_px = levels.target_price if levels.target_price > 0 else float(score_result.get("target_price") or (cur_px * 1.15))
    rr_val = levels.reward_risk if levels.reward_risk > 0 else float(score_result.get("reward_risk") or 2.0)

    return {
        **{k: score_result.get(k) for k in (
            "date", "ticker", "name", "sector", "timeframe",
            "technical_score", "fundamental_score", "sentiment_score",
            "macro_score", "event_risk_score", "final_score",
            "timeframe_scores", "preferred_timeframe",
            "stability_score", "opportunity_score", "risk_level", "reasoning",
            "technical",
        )},
        "current_price": cur_px,
        "stop_loss": stop_px,
        "target_price": target_px,
        "reward_risk": rr_val,
        "stop_loss_pct": levels.stop_loss_pct,
        "target_pct": levels.target_pct,
        "breakeven_price": levels.breakeven_price,
        "partial_target_price": levels.partial_target_price,
        "extended_target_price": levels.extended_target_price,
        "runner_target_price": levels.runner_target_price,
        "is_runner_candidate": is_runner,
        "time_stop_days": levels.time_stop_days,
        "max_runner_days": levels.max_runner_days,
        "action": decision["action"],
        "confidence": decision["confidence"],
        "setup_pattern": decision.get("setup_pattern", "NONE"),
        "vcp_ratio": decision.get("vcp_ratio", 1.0),
        "is_sector_decoupled": decision.get("is_sector_decoupled", False),
        "regime_context": decision.get("regime_context", ""),
        "action_rationale": decision["rationale"],
        "portfolio_note": decision.get("portfolio_note", ""),
        "warnings": decision.get("warnings", []),
        "holding": holding,
        "key_events": (score_result.get("event_risk") or {}).get("key_events", [])[:5],
        "company_events": (score_result.get("event_risk") or {}).get("company_events", [])[:4],
        "sector_events": (score_result.get("event_risk") or {}).get("sector_events", [])[:4],
        "macro_events": (score_result.get("event_risk") or {}).get("macro_events", [])[:4],
        "company_news": score_result.get("company_news", [])[:6],
        "sector_news": score_result.get("sector_news", [])[:6],
        "top_negative_news": (score_result.get("sentiment") or {}).get("top_negative", [])[:3],
        "top_positive_news": (score_result.get("sentiment") or {}).get("top_positive", [])[:3],
    }

