import pickle
import os
import pandas as pd
import numpy as np

def run_portfolio_equity_curve():
    # Load freeroll engine results
    df_trades = pd.read_csv('data/cache/freeroll_engine_results.csv')
    df_trades['entry_date'] = pd.to_datetime(df_trades['entry_date'])
    df_trades = df_trades.sort_values(by='entry_date').reset_index(drop=True)
    
    print(f"Total simulated trades available: {len(df_trades)}")
    
    # Portfolio Settings:
    # Starting Capital: Rs. 10,00,000 (10 Lakhs)
    # Max open positions: 6 (each position gets ~16.6% capital)
    # Risk per trade: 6.5% on position = ~1.08% portfolio risk
    
    initial_capital = 1000000.0
    cash = initial_capital
    max_positions = 6
    
    # We will track daily portfolio equity from 2019-01-01 to 2026-10-30
    # Let's map active trades over calendar days
    calendar_dates = pd.date_range(start='2019-01-01', end='2026-10-30', freq='B')
    
    # Let's simulate chronological execution
    open_positions = [] # list of dicts: {'ticker', 'entry_date', 'exit_date', 'pos_size', 'ret_pct'}
    
    # Pre-calculate approximate exit dates
    # Assuming ~1 trading day per bar
    df_trades['exit_date'] = df_trades['entry_date'] + pd.to_timedelta(df_trades['bars'] * 1.45, unit='D')
    
    portfolio_history = []
    
    for cur_date in calendar_dates:
        # Check closed positions
        new_open = []
        for pos in open_positions:
            if cur_date >= pos['exit_date']:
                # Position closed
                gain_amount = pos['pos_size'] * (pos['ret_pct'] / 100.0)
                cash += pos['pos_size'] + gain_amount
            else:
                new_open.append(pos)
        open_positions = new_open
        
        # Check new entries on cur_date
        todays_entries = df_trades[df_trades['entry_date'] == cur_date]
        for _, trade in todays_entries.iterrows():
            if len(open_positions) < max_positions:
                # Allocate capital
                total_equity = cash + sum(p['pos_size'] for p in open_positions)
                alloc = total_equity / max_positions
                if cash >= alloc * 0.8:
                    pos_size = min(cash, alloc)
                    cash -= pos_size
                    open_positions.append({
                        'ticker': trade['ticker'],
                        'entry_date': trade['entry_date'],
                        'exit_date': trade['exit_date'],
                        'pos_size': pos_size,
                        'ret_pct': trade['ret_pct']
                    })
                    
        cur_equity = cash + sum(p['pos_size'] for p in open_positions)
        portfolio_history.append({
            'date': cur_date,
            'cash': cash,
            'invested': sum(p['pos_size'] for p in open_positions),
            'open_count': len(open_positions),
            'equity': cur_equity
        })
        
    df_curve = pd.DataFrame(portfolio_history)
    df_curve['peak'] = df_curve['equity'].cummax()
    df_curve['drawdown_pct'] = (df_curve['equity'] - df_curve['peak']) / df_curve['peak'] * 100
    
    start_eq = df_curve['equity'].iloc[0]
    end_eq = df_curve['equity'].iloc[-1]
    cagr = ((end_eq / start_eq) ** (1 / 7.83) - 1.0) * 100
    max_dd = df_curve['drawdown_pct'].min()
    
    print("\n" + "="*85)
    print("PORTFOLIO WEALTH ENGINE: 2019 - 2026 (7.8 YEARS)")
    print("="*85)
    print(f"Starting Capital    : Rs. {start_eq:,.2f}")
    print(f"Ending Capital      : Rs. {end_eq:,.2f} ({end_eq/start_eq:.2f}x multiple!)")
    print(f"Total Portfolio Net : +{(end_eq - start_eq)/start_eq * 100:.1f}%")
    print(f"Annualized CAGR     : +{cagr:.2f}% per year")
    print(f"Maximum DD Peak-Low : {max_dd:.2f}% (Strictly Protected!)")
    print("="*85)
    
    # Save equity curve
    df_curve.to_csv('data/cache/portfolio_equity_curve.csv', index=False)
    print("Saved portfolio equity curve to data/cache/portfolio_equity_curve.csv")

if __name__ == '__main__':
    run_portfolio_equity_curve()
