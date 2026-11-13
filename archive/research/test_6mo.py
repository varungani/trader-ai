import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtesting.engine import run_simple_backtest

tickers = ['MPHASIS.NS', 'TRENT.NS', 'COFORGE.NS', 'KOTAKBANK.NS', 'AXISBANK.NS']
res = run_simple_backtest(
    tickers,
    period='6mo',
    initial_capital=10000.0,
    stop_loss_pct=0.07,
    target_pct=0.15,
    use_trailing_stop=False,
    use_trend_filter=True,
    max_position_pct=0.25,
)
print('6mo test result:')
print(f"Return: {res['total_return']:+.2f}% | WinRate: {res['win_rate']:.1f}% | Trades: {res['total_trades']}")
trades = res.get('detailed_results', {}).get('sample_trades', [])
for t in trades:
    print(t['ticker'], t['entry_date'], '->', t['exit_date'], 'pnl:', t['pnl'], 'pct:', t['pnl_percent'], t['reason'])
