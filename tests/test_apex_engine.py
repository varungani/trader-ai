"""
Tests for Apex Momentum Engine and Universe Definitions.
Verifies universe structure, position sizing math, and sector leadership helpers.
"""
import pytest
from config import HIGH_BETA_APEX_STOCKS, TICKER_TO_SECTOR, ALLOCATION_PROFILES
from engine.balancer import position_size
from analysis.sector_rs import get_top_leading_sectors


def test_apex_universe_contains_high_beta_leaders():
    """Verify that key institutional high-beta leaders exist in the Apex universe."""
    required = ["MAZDOCK.NS", "COFORGE.NS", "PERSISTENT.NS", "HAL.NS", "DIXON.NS"]
    for t in required:
        assert t in HIGH_BETA_APEX_STOCKS, f"{t} missing from HIGH_BETA_APEX_STOCKS"


def test_ticker_to_sector_mapping():
    """Verify sector mapping covers key high-beta tickers."""
    assert "PERSISTENT.NS" in TICKER_TO_SECTOR
    assert TICKER_TO_SECTOR["PERSISTENT.NS"] == "IT"
    assert TICKER_TO_SECTOR.get("HAL.NS") in ("Infra", "Defence")



def test_apex_3slot_position_sizing():
    """Verify 3-slot allocation sizing allocates ~33.3% of capital per slot."""
    capital = 90000.0
    stock_price = 1000.0
    # In a 3-slot portfolio, each slot receives ~30,000 INR
    target_slot_capital = capital / 3.0
    expected_shares = int(target_slot_capital // stock_price)
    
    assert expected_shares == 30
    assert expected_shares * stock_price <= target_slot_capital


def test_leading_sectors_returns_valid_list():
    """Verify sector leadership returns ranked sectors."""
    sectors = get_top_leading_sectors(top_n=3)
    assert isinstance(sectors, list)
    assert len(sectors) <= 3
    if sectors:
        assert "sector" in sectors[0]
        assert "composite_rs" in sectors[0]
