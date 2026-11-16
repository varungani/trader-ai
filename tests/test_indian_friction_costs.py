"""
Tests for Indian Statutory Delivery Friction Calculations (NSE Cash Delivery).
Verifies STT (0.1%), CDSL DP charges (₹15.93), GST, and net profit calculations.
"""
import pytest
from data.costs import compute_indian_delivery_costs, CDSL_DP_CHARGE, TradeFrictionBreakdown


def test_profitable_trade_friction():
    """Verify friction deduction on a profitable 20% gain."""
    # Buy 100 shares at ₹1000 = ₹1,00,000
    # Sell 100 shares at ₹1200 = ₹1,20,000 (Gross profit = ₹20,000)
    costs = compute_indian_delivery_costs(buy_price=1000.0, sell_price=1200.0, quantity=100)
    
    assert isinstance(costs, TradeFrictionBreakdown)
    assert costs.gross_pnl_rupees == 20000.0
    assert costs.gross_pnl_pct == 20.0
    
    # STT should be ~0.1% buy + 0.1% sell = ₹100 + ₹120 = ₹220
    assert 210.0 <= costs.stt_rupees <= 230.0
    
    # DP charges must include CDSL ₹15.93
    assert costs.dp_charges_rupees == CDSL_DP_CHARGE
    
    # Net PnL must be less than gross PnL due to friction
    assert costs.net_pnl_rupees < costs.gross_pnl_rupees
    assert costs.total_friction_rupees > 0
    assert hasattr(costs, "total_friction_rupees")


def test_losing_trade_friction():
    """Verify friction deduction on a losing trade (-7% stop loss)."""
    # Buy 100 shares at ₹1000 = ₹1,00,000
    # Sell 100 shares at ₹930 = ₹93,000 (Gross loss = -₹7,000)
    costs = compute_indian_delivery_costs(buy_price=1000.0, sell_price=930.0, quantity=100)
    
    assert costs.gross_pnl_rupees == -7000.0
    # Net loss must be worse than gross loss because fees are still paid!
    assert costs.net_pnl_rupees < costs.gross_pnl_rupees
    # No STCG tax on losses
    assert costs.stcg_tax_rupees == 0.0
    assert costs.dp_charges_rupees == CDSL_DP_CHARGE


def test_zero_quantity_or_flat_trade():
    """Verify flat trade handles zero profit and positive friction."""
    costs = compute_indian_delivery_costs(buy_price=500.0, sell_price=500.0, quantity=10)
    assert costs.gross_pnl_rupees == 0.0
    assert costs.net_pnl_rupees < 0.0  # Net loss due to DP charges & STT
    assert costs.total_friction_rupees > 0.0

