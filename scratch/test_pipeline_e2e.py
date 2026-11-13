import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.pipeline import run_pipeline

print("Running E2E pipeline with screener...")
brief = run_pipeline(
    universe_preset="extended",
    use_screener=True,
    screen_top_n=10,
    use_llm=False,
    paper_week=False,
    sync_broker=False
)

print("\n--- PIPELINE EXECUTION SUMMARY ---")
print("Date:", brief.get("date"))
print("Market Status:", brief.get("market_status"))
print("Top Picks Count:", len(brief.get("top_picks") or []))
print("All Recommendations Count:", len(brief.get("all_recommendations") or []))

print("\nTop 5 Actionable BUY Picks:")
for p in (brief.get("top_picks") or [])[:5]:
    print(f"  {p.get('ticker')}: Action={p.get('action')} | Score={p.get('final_score')} | Pattern={p.get('setup_pattern')} | Target={p.get('target_price')} | Stop={p.get('stop_loss')}")

print("\nSample 5 from Scored Universe (Tab 8):")
for r in (brief.get("all_recommendations") or [])[:5]:
    print(f"  {r.get('ticker')}: Score={r.get('final_score')} | Action={r.get('action')} | FastScreen={r.get('is_fast_screen', False)}")

