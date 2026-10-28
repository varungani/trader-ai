"""
TraderAI - Daily recommendation pipeline
1) Optional Kotak sync
2) Macro + news context once
3) Score holdings + watchlist
4) Persist to SQLite
5) Return structured brief
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    DAILY_TOP_PICKS,
    DEFAULT_ALLOCATION_PROFILE,
    DEFAULT_UNIVERSE_PRESET,
    MONTHLY_MF_BUDGET,
    MONTHLY_STOCK_BUDGET,
    SCREEN_TOP_N,
)
from analysis.macro import compute_macro_score
from data.db import get_connection, save_daily_brief, save_daily_score
from data.news_oss import fetch_macro_news_bundle
from engine.balancer import build_balance_plan
from engine.llm_review import review_recommendations
from engine.monthly_plan import build_monthly_plan
from engine.paper_week import (
    open_paper_from_deploys,
    real_money_allowed,
    record_daily_review,
    start_paper_week,
)
from engine.recommender import build_recommendation
from engine.scorer import score_stock
from engine.screener import select_deep_score_universe
from portfolio.manager import held_tickers, portfolio_summary, sync_from_kotak

logger = logging.getLogger(__name__)


def _flatten_macro_news(bundles: dict) -> list[dict]:
    out = []
    for items in bundles.values():
        out.extend(items or [])
    return out


def run_pipeline(
    tickers: Optional[list[str]] = None,
    timeframe: str = "short_term",
    include_holdings: bool = True,
    sync_broker: bool = False,
    totp: Optional[str] = None,
    persist: bool = True,
    max_watchlist: int = 15,
    allocation_profile: str = DEFAULT_ALLOCATION_PROFILE,
    capital: Optional[float] = None,
    use_llm: bool = False,
    paper_week: bool = False,
    universe_preset: str = DEFAULT_UNIVERSE_PRESET,
    screen_top_n: int = SCREEN_TOP_N,
    use_screener: bool = True,
    stock_budget: Optional[float] = None,
    mf_budget: Optional[float] = None,
) -> dict:
    """
    Run analysis and produce recommendations + balance + monthly SIP plan.

    Args:
        use_screener: pre-scan broad universe, deep-score only top_n (+ holdings)
        universe_preset: nifty50 | nifty100 | midcap | extended | all
        stock_budget / mf_budget: monthly fresh capital (default 10k / 10k)
    """
    money_gate = real_money_allowed()
    if money_gate.get("allowed"):
        logger.warning("Real-money flag unlocked — still no order placement in this codebase.")

    broker_sync = None
    if sync_broker:
        broker_sync = sync_from_kotak(totp=totp, prompt=False)
        if not broker_sync.get("ok"):
            logger.warning(f"Broker sync skipped: {broker_sync.get('error')}")

    port = portfolio_summary()
    holdings_map = {h["symbol"]: h for h in (port.get("holdings") or [])}
    held = held_tickers() if include_holdings else []

    screen_info = None
    if tickers:
        universe = list(tickers)
    elif use_screener:
        screen_info = select_deep_score_universe(
            preset=universe_preset,
            top_n=screen_top_n or max_watchlist,
            always_include=held,
        )
        universe = screen_info["deep_score_tickers"]
        logger.info(
            f"Screener: {screen_info['universe_size']} scanned -> "
            f"{len(universe)} deep-scored ({universe_preset})"
        )
    else:
        from engine.screener import get_universe

        universe = get_universe(universe_preset)[:max_watchlist]
        for t in held:
            if t not in universe:
                universe.insert(0, t)

    # Deduplicate preserving order
    seen = set()
    cleaned = []
    for t in universe:
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    universe = cleaned

    logger.info(f"Pipeline universe: {len(universe)} tickers ({timeframe})")

    macro = compute_macro_score()
    news_bundles = fetch_macro_news_bundle()
    macro_news = _flatten_macro_news(news_bundles)

    recommendations = []
    for ticker in universe:
        try:
            scored = score_stock(
                ticker,
                timeframe=timeframe,
                macro_score=macro,
                macro_news=macro_news,
            )
            rec = build_recommendation(
                scored,
                holding=holdings_map.get(ticker),
                portfolio_summary=port,
            )
            if screen_info:
                hit = next(
                    (s for s in screen_info.get("screened") or [] if s["ticker"] == ticker),
                    None,
                )
                if hit:
                    rec["screen_score"] = hit.get("screen_score")
                    rec["screen_ret_1m_pct"] = hit.get("ret_1m_pct")
                    rec["screen_rvol"] = hit.get("rvol")
                    rec["setup_pattern"] = hit.get("setup_pattern")
            recommendations.append(rec)
        except Exception as e:
            logger.error(f"Failed scoring {ticker}: {e}")
            recommendations.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "final_score": 50,
                    "action": "HOLD",
                    "reasoning": f"Scoring failed: {e}",
                    "error": str(e),
                }
            )

    recommendations.sort(key=lambda r: float(r.get("final_score") or 0), reverse=True)

    from portfolio.manager import load_portfolio

    raw = load_portfolio()
    if "cash" in raw:
        port = dict(port)
        port["cash"] = float(raw.get("cash") or 0)

    # For sizing, default capital = current portfolio + this month's stock SIP
    stock_budget = float(stock_budget if stock_budget is not None else MONTHLY_STOCK_BUDGET)
    mf_budget = float(mf_budget if mf_budget is not None else MONTHLY_MF_BUDGET)
    capital_base = capital
    if capital_base is None:
        capital_base = float(port.get("total_current_value") or 0) + stock_budget
        if capital_base <= 0:
            capital_base = stock_budget

    balance = build_balance_plan(
        recommendations,
        portfolio=port,
        profile_name=allocation_profile,
        capital=capital_base,
    )
    recommendations = balance.get("enriched_recommendations") or recommendations

    llm_bundle = {"reviews": [], "summary": {"reviewed": 0, "llm_backend_available": False}}
    if use_llm:
        logger.info("Running Analyst LLM + independent Judge LLM")
        llm_bundle = review_recommendations(recommendations, macro=macro)
        recommendations = llm_bundle.get("recommendations") or recommendations
        balance = build_balance_plan(
            recommendations,
            portfolio=port,
            profile_name=allocation_profile,
            capital=capital_base,
        )
        recommendations = balance.get("enriched_recommendations") or recommendations
        allow = {
            r["ticker"]
            for r in llm_bundle.get("reviews") or []
            if (r.get("judge") or {}).get("allow_paper_trade")
        }
        balance["deploy_plan"] = [
            d for d in (balance.get("deploy_plan") or []) if d.get("ticker") in allow
        ]

    recommendations.sort(key=lambda r: float(r.get("final_score") or 0), reverse=True)

    monthly = build_monthly_plan(
        recommendations,
        balance.get("deploy_plan") or [],
        stock_budget=stock_budget,
        mf_budget=mf_budget,
    )

    buys = [r for r in recommendations if r.get("action") in ("BUY", "STRONG_BUY")]
    sells = [r for r in recommendations if r.get("action") in ("SELL", "STRONG_SELL", "TRIM", "AVOID")]
    # Complete diagnosis for all holdings currently in portfolio
    portfolio_actions = [
        r for r in recommendations
        if r.get("holding")
    ]
    for t in balance.get("trim_plan") or []:
        if not any(p.get("ticker") == t.get("ticker") for p in portfolio_actions):
            portfolio_actions.append(t)

    regime_gate_active = not macro.get("is_regime_gate_cleared", True) or macro.get("no_trade_today", False)

    # ─── Sector Decoupling Engine (Alpha Over Broad Beta) ─────────────────────
    # If broad NIFTY 50 is below 50 SMA (regime gate active), check if high-conviction
    # Stage-2 sector leaders are actively breaking out with institutional volume.
    decoupled_picks = []
    if regime_gate_active and buys:
        for b in buys:
            score = float(b.get("final_score") or 0)
            sector_info = b.get("sector_relative_strength") or {}
            sec_status = sector_info.get("status", "NEUTRAL")
            sec_rs = float(sector_info.get("relative_strength_pct") or 0.0)
            vol_ratio = float(b.get("screen_rvol") or (b.get("technical") or {}).get("indicators", {}).get("volume", {}).get("volume_ratio") or 1.0)

            # An elite decoupled leader has score >= 65, non-lagging sector
            if score >= 65 and sec_status not in ("LAGGING", "SEVERE_DRAG"):
                b["is_sector_decoupled"] = True
                b["regime_context"] = f"SECTOR_ALPHA_DECOUPLED ({sec_rs:+.1f}% RS)"
                decoupled_picks.append(b)

    sector_decoupled_active = False
    if regime_gate_active:
        if decoupled_picks:
            top_picks = decoupled_picks[:DAILY_TOP_PICKS]
            no_trade_today = False
            sector_decoupled_active = True
            no_trade_reason = None
        else:
            top_picks = []
            no_trade_today = True
            no_trade_reason = macro.get("regime_gate_reason", "Market Regime Gate active (NIFTY 50 below 50-day SMA or elevated volatility). Cash preservation enforced.")
    elif buys:
        top_picks = buys[:DAILY_TOP_PICKS]
        no_trade_today = False
        no_trade_reason = None
    else:
        top_picks = []
        no_trade_today = True
        no_trade_reason = "No stocks in scanned universe cleared the minimum score (≥65) and 2:1 Reward-to-Risk criteria today. Sitting in cash preserves capital."

    paper_state = None
    paper_opened = []
    if paper_week:
        start_paper_week(force=False)
        judged = [r.get("judge") or {} for r in (llm_bundle.get("reviews") or [])]
        if use_llm and judged:
            # Prefer monthly stock allocations for paper opens when present
            paper_deploys = []
            for a in monthly.get("stock_allocations") or []:
                if a.get("status") == "ALLOCATE":
                    paper_deploys.append(
                        {
                            "ticker": a["ticker"],
                            "qty": a["qty"],
                            "rupees": a["rupees"],
                            "stop_loss": a.get("stop_loss"),
                            "target_price": a.get("target_price"),
                            "preferred_timeframe": a.get("preferred_timeframe"),
                            "sleeve": a.get("sleeve"),
                            "reward_risk": a.get("reward_risk"),
                        }
                    )
            paper_opened = open_paper_from_deploys(
                paper_deploys or (balance.get("deploy_plan") or []),
                judged,
                timeframe=timeframe,
            )
        paper_state = record_daily_review(
            brief_summary=_market_summary(macro, news_bundles),
            judge_results=judged,
            opened=paper_opened,
        )

    from data.market_calendar import get_market_status
    from engine.validator import (
        record_daily_snapshot,
        audit_and_resolve_forward_trades,
        compute_institutional_scorecards,
    )

    forward_val_report = {}
    try:
        # 1. Update any existing open forward trades with live MTM & resolve target/stop exits
        audit_and_resolve_forward_trades()
        # 2. Record immutable 09:30 morning snapshot of today's actionable recommendations
        judged_reviews = llm_bundle.get("reviews") or []
        record_daily_snapshot(recommendations, macro=macro, judge_reviews=judged_reviews)
        # 3. Calculate 4 institutional forward scorecards
        forward_val_report = compute_institutional_scorecards()
    except Exception as e:
        logger.warning(f"Forward validation engine step failed: {e}")

    # ─── OPTION C: CROSS-MARKET MULTI-ASSET MESH (INDIA -> US BRIDGE) ───
    cross_market_bridge = None
    try:
        from engine.us_engine import get_us_market_status, fetch_us_realtime_data, analyze_us_market
        us_status = get_us_market_status()
        us_data = fetch_us_realtime_data()
        us_analysis = analyze_us_market(us_data)
        top_us = [
            c for c in us_analysis.get("candidates", [])
            if "BUY" in c.get("verdict", "") or "HOLD" in c.get("verdict", "")
        ][:6]
        cross_market_bridge = {
            "active": True,
            "india_no_trade": no_trade_today,
            "india_regime_gate": regime_gate_active,
            "reason": (
                "Indian Market Gate Active (Cash Defense / Zero Setups). Option C Mesh dynamically routes momentum capital to Wall Street (INDmoney)."
                if no_trade_today
                else "Cross-Market Barbell Active (Both Indian & US opportunities available for 24h non-overlapping compounding)."
            ),
            "us_status": us_status,
            "macro": us_analysis.get("macro", {}),
            "top_candidates": top_us,
        }
    except Exception as e:
        logger.warning(f"Cross-market US bridge calculation failed: {e}")

    brief = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market_status": get_market_status(),
        "timeframe": timeframe,
        "allocation_profile": allocation_profile,
        "universe_preset": universe_preset,
        "screen": screen_info,
        "monthly_plan": monthly,
        "market_summary": _market_summary(macro, news_bundles),
        "macro": macro,
        "portfolio": port,
        "balance": balance,
        "llm": llm_bundle,
        "paper_week": paper_state,
        "paper_opened": paper_opened,
        "forward_validation": forward_val_report,
        "real_money": real_money_allowed(),
        "top_picks": top_picks,
        "no_trade_today": no_trade_today,
        "no_trade_reason": no_trade_reason,
        "regime_gate_active": regime_gate_active,
        "sector_decoupled_active": sector_decoupled_active,
        "sell_candidates": sells[:DAILY_TOP_PICKS],
        "portfolio_actions": portfolio_actions,
        "all_recommendations": recommendations,
        "broker_sync": broker_sync,
        "news_counts": {k: len(v) for k, v in news_bundles.items()},
        "cross_market_bridge": cross_market_bridge,
    }

    if persist:
        _persist(brief)

    return brief


def _market_summary(macro: dict, news_bundles: dict) -> str:
    obs = "; ".join((macro.get("observations") or [])[:3]) or "No macro observations."
    n_market = len(news_bundles.get("market") or [])
    n_geo = len(news_bundles.get("geopolitics") or [])
    n_pol = len(news_bundles.get("policy") or [])
    return (
        f"Regime {macro.get('regime')} ({macro.get('score')}/100). {obs} "
        f"News ingested — market:{n_market}, policy:{n_pol}, geopolitics:{n_geo}."
    )


def _persist(brief: dict) -> None:
    conn = get_connection()
    try:
        for rec in brief.get("all_recommendations") or []:
            if rec.get("error") and not rec.get("technical_score"):
                continue
            save_daily_score(
                conn,
                {
                    "date": brief["date"],
                    "ticker": rec["ticker"],
                    "timeframe": rec.get("timeframe", brief["timeframe"]),
                    "technical_score": rec.get("technical_score"),
                    "fundamental_score": rec.get("fundamental_score"),
                    "sentiment_score": rec.get("sentiment_score"),
                    "macro_score": rec.get("macro_score"),
                    "event_risk_score": rec.get("event_risk_score"),
                    "final_score": rec.get("final_score"),
                    "action": rec.get("action"),
                    "reasoning": rec.get("reasoning") or rec.get("action_rationale"),
                    "risk_level": rec.get("risk_level"),
                    "stop_loss": rec.get("stop_loss"),
                    "target_price": rec.get("target_price"),
                },
            )
        save_daily_brief(
            conn,
            brief["date"],
            {
                "market_summary": brief["market_summary"],
                "top_picks": [
                    {
                        "ticker": r.get("ticker"),
                        "action": r.get("action"),
                        "final_score": r.get("final_score"),
                        "reasoning": r.get("reasoning"),
                    }
                    for r in brief.get("top_picks") or []
                ],
                "portfolio_actions": [
                    {
                        "ticker": r.get("ticker"),
                        "action": r.get("action"),
                        "final_score": r.get("final_score"),
                        "portfolio_note": r.get("portfolio_note"),
                    }
                    for r in brief.get("portfolio_actions") or []
                ],
            },
        )
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_pipeline(max_watchlist=8, persist=True, sync_broker=False)
    print(result["market_summary"])
    print("\nTop picks:")
    for r in result["top_picks"][:5]:
        print(
            f"  {r.get('action'):12} {r.get('ticker'):15} score={r.get('final_score')} "
            f"risk={r.get('risk_level')}"
        )
