"""
Tests for Portfolio Manager.
Verifies loading, saving, upserting, and removing local holdings.
"""
import pytest
from portfolio.manager import load_portfolio, upsert_holding, remove_holding, portfolio_summary


def test_upsert_and_remove_holding():
    """Verify adding, updating, and removing a holding."""
    test_ticker = "UNITTEST.NS"
    
    # 1. Add holding
    upsert_holding(test_ticker, quantity=10, avg_price=100.0, current_price=110.0)
    port = load_portfolio()
    symbols = [h["symbol"] for h in port.get("holdings", [])]
    assert test_ticker in symbols
    
    holding = next(h for h in port["holdings"] if h["symbol"] == test_ticker)
    assert holding["quantity"] == 10
    assert holding["avg_price"] == 100.0
    assert holding["current_price"] == 110.0
    assert holding["pnl"] == 100.0
    assert holding["pnl_percent"] == 10.0
    
    # 2. Update holding
    upsert_holding(test_ticker, quantity=20, avg_price=100.0, current_price=120.0)
    port = load_portfolio()
    updated = next(h for h in port["holdings"] if h["symbol"] == test_ticker)
    assert updated["quantity"] == 20
    assert updated["market_value"] == 2400.0
    
    # 3. Remove holding
    remove_holding(test_ticker)
    port_after = load_portfolio()
    symbols_after = [h["symbol"] for h in port_after.get("holdings", [])]
    assert test_ticker not in symbols_after


def test_portfolio_summary_structure():
    """Verify portfolio summary dictionary contains required keys."""
    summary = portfolio_summary()
    assert isinstance(summary, dict)
    assert "total_value" in summary
    assert "holdings_count" in summary
    assert "total_pnl" in summary

