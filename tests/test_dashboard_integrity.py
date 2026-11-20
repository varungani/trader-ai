"""
Tests for TraderAI Dashboard and Configuration Integrity.
Ensures app.py, config.py, and core environment bridges compile and load without errors.
"""
import ast
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_config_loads_properly():
    """Verify config.py contains required trading profiles and universe definitions."""
    import config
    assert hasattr(config, "ALLOCATION_PROFILES"), "Missing ALLOCATION_PROFILES in config"
    assert "apex_3slot" in config.ALLOCATION_PROFILES, "Missing apex_3slot profile"
    assert hasattr(config, "HIGH_BETA_APEX_STOCKS"), "Missing HIGH_BETA_APEX_STOCKS"
    assert len(config.HIGH_BETA_APEX_STOCKS) >= 20, "Apex stock universe too small"
    assert config.MONTHLY_STOCK_BUDGET > 0, "Stock budget must be positive"


def test_app_syntax_compiles():
    """Verify app.py syntax is 100% valid Python AST before Streamlit attempts to run it."""
    app_path = os.path.join(ROOT, "app.py")
    assert os.path.exists(app_path), "app.py does not exist"
    
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()
    
    # ast.parse will raise SyntaxError if anything is invalid
    parsed = ast.parse(code, filename="app.py")
    assert parsed is not None, "Failed to parse app.py AST"


def test_market_calendar_status():
    """Verify market calendar reports valid status dict with expected keys."""
    from data.market_calendar import get_market_status
    status = get_market_status()
    assert isinstance(status, dict)
    assert "is_open" in status
    assert "badge" in status
    assert "detail" in status


def test_broker_configuration_check():
    """Verify broker configuration detection does not crash without credentials."""
    from data.broker import is_configured
    configured = is_configured()
    assert isinstance(configured, bool)


def test_format_display_date_behavior():
    """Verify format_display_date formats post-market audit fills and standard dates cleanly."""
    from app import format_display_date
    assert format_display_date("2026-11-18 15:30") == "18 Nov (Market Hours)"
    assert format_display_date("2026-11-18 (Market Hours)") == "18 Nov (Market Hours)"
    assert format_display_date("2026-11-18 (Intraday)") == "18 Nov (Market Hours)"
    assert format_display_date("2026-11-18 09:20") == "18 Nov 09:20"
    assert format_display_date("2026-11-18") == "18 Nov"
    assert format_display_date("") == "—"


