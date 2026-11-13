import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.pipeline import run_pipeline

print("Running pipeline for High-Beta Rockets on 29 Oct 2026...", flush=True)

brief = run_pipeline(
    universe_preset="high_beta_rockets",
    timeframe="short_term",
    use_screener=True,
    screen_top_n=20,
    persist=True,
    paper_week=True,
)

print(f"\nMarket Regime: {brief.get('macro', {}).get('regime')} (Score: {brief.get('macro', {}).get('score')})")
print(f"Top Picks Count: {len(brief.get('top_picks', []))}")
for p in brief.get("top_picks", []):
    print(f"⭐ {p['ticker']} : ₹{p.get('current_price')} | Score: {p.get('final_score')} | Action: {p.get('action')} | Stop: ₹{p.get('stop_loss')} | Target: ₹{p.get('target_price')}")

print("\nTop 5 Scored Candidates from Scored Universe:")
for r in (brief.get("all_recommendations") or [])[:5]:
    print(f"  • {r.get('ticker')}: Score {r.get('final_score')} | Action: {r.get('action')} | Tech: {r.get('technical_score')}")
