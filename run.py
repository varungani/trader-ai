"""
TraderAI CLI
  python run.py --universe extended --screen-top 20
  python run.py --stock-budget 10000 --mf-budget 10000 --llm --paper-week
"""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main():
    parser = argparse.ArgumentParser(description="TraderAI open-source recommender")
    parser.add_argument("--timeframe", default="mid_term", choices=["short_term", "mid_term", "long_term"])
    parser.add_argument("--profile", default="balanced", choices=["balanced", "conservative", "growth"])
    parser.add_argument(
        "--universe",
        default="nifty500",
        choices=["nifty500", "nifty50", "nifty100", "midcap", "etfs", "extended", "all"],
        help="Stock universe to scan (default: nifty500 ~500 NSE names)",
    )
    parser.add_argument("--screen-top", type=int, default=20, help="Deep-score top N after cheap pre-screen")
    parser.add_argument("--no-screener", action="store_true", help="Skip pre-screen; take first N of universe")
    parser.add_argument("--tickers", default="", help="Comma-separated Yahoo tickers (skips universe scan)")
    parser.add_argument("--watchlist", type=int, default=20, help="Fallback size if screener off")
    parser.add_argument("--stock-budget", type=float, default=0, help="Monthly stock SIP INR (default 10000)")
    parser.add_argument("--mf-budget", type=float, default=0, help="Monthly MF SIP INR (default 10000)")
    parser.add_argument("--capital", type=float, default=0, help="Capital override for risk sizing")
    parser.add_argument("--sync-broker", action="store_true", help="Sync Kotak Neo holdings first")
    parser.add_argument("--totp", default="", help="Kotak TOTP (or set KOTAK_TOTP_SECRET)")
    parser.add_argument("--llm", action="store_true", help="Run Analyst + separate Judge LLMs")
    parser.add_argument("--paper-week", action="store_true", help="Shadow-trade judge-approved deploys")
    parser.add_argument("--paper-week-status", action="store_true", help="Show paper-week gate status")
    parser.add_argument("--paper-week-extend", action="store_true", help="Extend paper week by 7 days")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON brief")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.paper_week_status or args.paper_week_extend:
        from engine.paper_week import extend_paper_week, load_paper_week, real_money_allowed

        if args.paper_week_extend:
            state = extend_paper_week(7)
        else:
            state = load_paper_week()
        gate = real_money_allowed()
        print(json.dumps({"paper_week": state, "real_money": gate}, indent=2, default=str))
        return

    from engine.pipeline import run_pipeline

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()] or None
    use_llm = args.llm or args.paper_week

    brief = run_pipeline(
        tickers=tickers,
        timeframe=args.timeframe,
        include_holdings=True,
        sync_broker=args.sync_broker,
        totp=args.totp or None,
        persist=not args.no_persist,
        max_watchlist=args.watchlist,
        allocation_profile=args.profile,
        capital=args.capital or None,
        use_llm=use_llm,
        paper_week=args.paper_week,
        universe_preset=args.universe,
        screen_top_n=args.screen_top,
        use_screener=not args.no_screener and tickers is None,
        stock_budget=args.stock_budget or None,
        mf_budget=args.mf_budget or None,
    )

    if args.json:
        slim = {
            "market_summary": brief["market_summary"],
            "universe_preset": brief.get("universe_preset"),
            "screen": {
                "universe_size": (brief.get("screen") or {}).get("universe_size"),
                "top": (brief.get("screen") or {}).get("screened", [])[:15],
            },
            "monthly_plan": brief.get("monthly_plan"),
            "balance": {
                k: brief["balance"].get(k)
                for k in (
                    "profile", "profile_label", "targets", "current_mix", "gaps_pct",
                    "balance_health", "heat_pct", "deploy_plan", "trim_plan", "guidance",
                )
            },
            "llm": brief.get("llm"),
            "paper_week": brief.get("paper_week"),
            "real_money": brief.get("real_money"),
            "top_picks": brief["top_picks"],
            "sell_candidates": brief["sell_candidates"],
            "portfolio": brief["portfolio"],
            "news_counts": brief["news_counts"],
        }
        print(json.dumps(slim, indent=2, default=str))
        return

    print("\n=== MARKET ===")
    print(brief["market_summary"])

    screen = brief.get("screen") or {}
    if screen:
        print(f"\n=== SCREENER ({brief.get('universe_preset')}) ===")
        print(f"  scanned={screen.get('universe_size')} deep_scored={len(screen.get('deep_score_tickers') or [])}")
        for s in (screen.get("screened") or [])[:10]:
            print(
                f"  {s.get('ticker'):14} screen={s.get('screen_score')} "
                f"1m={s.get('ret_1m_pct')}% liq={s.get('avg_value_cr')}cr"
            )

    mp = brief.get("monthly_plan") or {}
    print("\n=== MONTHLY PLAN (SIP) ===")
    for line in mp.get("guidance") or []:
        print("  -", line.encode("ascii", "replace").decode("ascii"))
    print("  Stocks:")
    for a in mp.get("stock_allocations") or []:
        print(
            f"    {a.get('status'):16} {str(a.get('ticker', a.get('scheme_code', ''))):14} "
            f"qty={a.get('qty')} INR {a.get('rupees')}"
        )
    print("  Mutual funds:")
    for a in mp.get("mf_allocations") or []:
        name = (a.get("scheme_name") or a.get("note") or "")[:40]
        print(f"    {a.get('status'):16} {a.get('scheme_code', ''):8} INR {a.get('rupees')}  {name}")

    bal = brief.get("balance") or {}
    print("\n=== BALANCE ===")
    for line in bal.get("guidance") or []:
        print("  -", line.encode("ascii", "replace").decode("ascii"))

    llm = brief.get("llm") or {}
    if llm.get("summary"):
        print("\n=== LLM JUDGE ===")
        print(" ", llm.get("summary"))
        for r in llm.get("reviews") or []:
            j = r.get("judge") or {}
            print(
                f"  {r.get('ticker')}: {r.get('action_original')} -> {r.get('action_final')} | "
                f"verdict={j.get('verdict')} trust={j.get('overall_trust')} paper={j.get('allow_paper_trade')}"
            )

    pw = brief.get("paper_week")
    if pw:
        print("\n=== PAPER WEEK ===")
        print(f"  status={pw.get('status')} unlocked={pw.get('real_money_unlocked')}")
        print(f"  gate={pw.get('gate_detail')}")

    print("\n=== TOP PICKS ===")
    if brief.get("no_trade_today"):
        print(f"  [CASH PRESERVATION ACTIVE] {brief.get('no_trade_reason')}")
        print("  New BUY recommendations are gated to protect capital. Sitting in cash.\n")
        all_recs = brief.get("all_recommendations") or []
        if all_recs:
            print("=== TOP WATCHLIST CANDIDATES (Gated by Macro Downtrend) ===")
            for r in all_recs[:10]:
                print(
                    f"  {str(r.get('ticker', '?')):14} score={r.get('final_score')} "
                    f"price=Rs {r.get('current_price')} stop=Rs {r.get('stop_loss')} "
                    f"target=Rs {r.get('target_price')} R:R={r.get('reward_risk')}x"
                )
    elif brief.get("top_picks"):
        for r in brief["top_picks"][:10]:
            print(
                f"  {str(r.get('action', '?')):12} {str(r.get('ticker', '?')):14} "
                f"score={r.get('final_score')} price=Rs {r.get('current_price')} "
                f"stop=Rs {r.get('stop_loss')} target=Rs {r.get('target_price')} R:R={r.get('reward_risk')}x"
            )
    else:
        print("  None (no stocks met the entry criteria today)")


if __name__ == "__main__":
    main()
    sys.exit(0)
