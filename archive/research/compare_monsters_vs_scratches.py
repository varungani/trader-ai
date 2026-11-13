import pandas as pd
import numpy as np

def analyze_monsters_vs_scratches():
    df = pd.read_csv('data/cache/freeroll_engine_results.csv')
    print(f"Total trades loaded: {len(df)}")
    
    monsters = df[df['ret_pct'] >= 50.0]
    great_trades = df[(df['ret_pct'] >= 20.0) & (df['ret_pct'] < 50.0)]
    scratches_and_losses = df[df['ret_pct'] <= 2.0]
    
    print("\n" + "="*85)
    print("FORENSIC COMPARISON: MONSTERS (>= +50%) vs REGULAR TRADES vs SCRATCHES/LOSSES")
    print("="*85)
    print(f"Monster Trades (>= +50%)  : {len(monsters)} trades | Avg Return: +{monsters['ret_pct'].mean():.1f}% | Avg Holding: {monsters['bars'].mean():.1f} bars ({monsters['bars'].mean()/21:.1f} mos)")
    print(f"Solid Trades (+20% to +50%): {len(great_trades)} trades | Avg Return: +{great_trades['ret_pct'].mean():.1f}% | Avg Holding: {great_trades['bars'].mean():.1f} bars ({great_trades['bars'].mean()/21:.1f} mos)")
    print(f"Scratches / Losses (<= +2%): {len(scratches_and_losses)} trades | Avg Return: {scratches_and_losses['ret_pct'].mean():.1f}% | Avg Holding: {scratches_and_losses['bars'].mean():.1f} bars")
    
    print("\nTop 20 Monster Trades Breakdown:")
    for _, r in monsters.sort_values(by='ret_pct', ascending=False).head(20).iterrows():
        print(f"  {r['ticker']:<14} | Date: {str(r['entry_date'])[:10]} | Net Gain: +{r['ret_pct']:>6.1f}% | Bars: {int(r['bars']):>3} ({r['bars']/21:.1f} mos)")
        
if __name__ == '__main__':
    analyze_monsters_vs_scratches()
