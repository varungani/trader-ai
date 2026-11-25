"""
Unit tests for TelegramNotifier.
Validates:
  - Configuration detection (enabled, token, chat_id)
  - HTTP POST requests to api.telegram.org with mock responses
  - Correct payload formatting and markdown syntax
  - Specialized alert formats: breakout fill, breakeven lock, target hit, stop loss, velocity kill
  - Graceful handling of network/HTTP failures
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from bot.telegram_notifier import TelegramNotifier


@pytest.fixture
def configured_notifier():
    return TelegramNotifier(
        enabled=True,
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ",
        chat_id="987654321",
    )


def test_telegram_notifier_not_configured():
    notifier = TelegramNotifier(enabled=False)
    assert not notifier.is_configured()
    assert notifier.send_message("Hello") is False


def test_telegram_notifier_send_message_success(configured_notifier):
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        success = configured_notifier.send_message("Test message")
        assert success is True

        # Verify URL and payload
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert "api.telegram.org/bot123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ/sendMessage" in req.full_url
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["chat_id"] == "987654321"
        assert payload["text"] == "Test message"
        assert payload["parse_mode"] == "Markdown"


def test_telegram_notifier_notify_breakout_fill(configured_notifier):
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_breakout_fill(
            ticker="UNIONBANK.NS",
            fill_price=209.70,
            target_price=234.86,
            stop_loss=201.31,
            shares=95,
            strategy_track="Track B (GTT Breakout)",
            sector="Banking",
            pattern="PRE_IGNITION_COIL",
        )
        assert success is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "UNIONBANK" in sent_text
        assert "209.70" in sent_text
        assert "234.86" in sent_text
        assert "201.31" in sent_text
        assert "PRE_IGNITION_COIL" in sent_text


def test_telegram_notifier_notify_breakeven_lock(configured_notifier):
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_breakeven_lock(
            ticker="UNIONBANK.NS",
            entry_price=209.70,
            current_price=220.50,
            pnl_pct=5.15,
            new_stop_loss=210.33,
        )
        assert success is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "BREAKEVEN STOP LOCKED" in sent_text
        assert "+5.15%" in sent_text
        assert "210.33" in sent_text


def test_telegram_notifier_notify_target_hit(configured_notifier):
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_target_hit(
            ticker="PNB.NS",
            entry_price=151.67,
            exit_price=169.87,
            pnl_rupees=3986.80,
            pnl_pct=12.0,
        )
        assert success is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "TARGET HIT" in sent_text
        assert "PNB" in sent_text
        assert "+12.00%" in sent_text


def test_telegram_notifier_notify_stop_loss_hit(configured_notifier):
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_stop_loss_hit(
            ticker="DEEPAKFERT.NS",
            entry_price=1460.0,
            exit_price=1401.6,
            loss_inr=-1284.8,
            loss_pct=-4.0,
            is_breakeven=False,
        )
        assert success is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "STOP LOSS EXECUTED" in sent_text
        assert "DEEPAKFERT" in sent_text


def test_telegram_notifier_notify_velocity_kill(configured_notifier):
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_velocity_kill(
            ticker="TATASTEEL.NS",
            entry_price=140.0,
            exit_price=140.5,
            days_held=3,
            pnl_pct=0.36,
            freed_capital_inr=19951.0,
        )
        assert success is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "72H VELOCITY KILL" in sent_text
        assert "TATASTEEL" in sent_text
        assert "3 sessions" in sent_text


def test_telegram_notifier_notify_live_buy_signal(configured_notifier):
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_live_buy_signal(
            ticker="CANBK.NS",
            current_price=136.80,
            pivot_trigger=136.50,
            buy_ceiling=138.50,
            target_price=153.20,
            stop_loss=131.30,
            shares=146,
            sector="Banking",
            pattern="INSTITUTIONAL_IGNITION",
        )
        assert success is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "LIVE BUY SIGNAL: INTRADAY BREAKOUT" in sent_text
        assert "CANBK" in sent_text
        assert "136.80" in sent_text
        assert "138.50" in sent_text
        assert "153.20" in sent_text
        assert "131.30" in sent_text
        assert "146 shares" in sent_text
        assert "CNC (Delivery / Cash)" in sent_text


def test_telegram_notifier_notify_daily_recap_includes_all_9_tracks(configured_notifier):
    sample_summary = {
        "winner": "Track 6 Leading",
        "track_algo4": {"total_pnl_inr": -447.0, "total_pnl_pct": -0.45, "open_count": 4, "closed_count": 1, "pending_count": 22, "win_rate": 0.0},
        "option_3": {"total_pnl_inr": -447.0, "total_pnl_pct": -0.45, "open_count": 4, "closed_count": 1, "pending_count": 30, "win_rate": 0.0},
        "track_algo5": {"total_pnl_inr": -919.0, "total_pnl_pct": -0.92, "open_count": 2, "closed_count": 1, "pending_count": 1, "win_rate": 0.0},
        "option_2": {"total_pnl_inr": 274.96, "total_pnl_pct": 0.27},
        "track_c": {"total_pnl_inr": -447.0, "total_pnl_pct": -0.45},
        "track_apex_compounder": {"total_pnl_inr": 1324.64, "total_pnl_pct": 1.32, "open_count": 3, "closed_count": 0, "pending_count": 22, "win_rate": 0.0},
        "track_conviction_2slot": {"total_pnl_inr": 1140.02, "total_pnl_pct": 1.14, "open_count": 2, "closed_count": 0, "pending_count": 15, "win_rate": 0.0},
        "track_apex_1slot": {"total_pnl_inr": 489.70, "total_pnl_pct": 0.49, "open_count": 1, "closed_count": 0, "pending_count": 7, "win_rate": 0.0},
        "track_monthly_swing": {"total_pnl_inr": 486.75, "total_pnl_pct": 0.49, "open_count": 4, "closed_count": 0, "pending_count": 29, "win_rate": 0.0},
    }
    with patch.object(configured_notifier, "send_message", return_value=True) as mock_send:
        success = configured_notifier.notify_daily_recap(sample_summary)
        assert success is True
        sent_text = mock_send.call_args[0][0]
        assert "9-WAY PERFORMANCE RECAP" in sent_text
        for label in ["Track 6", "Track 7", "Track 8", "Track 9", "Track 1", "Track 5"]:
            assert label in sent_text

        # Verify A/B Legacy comparison renders when legacy summaries exist
        sample_summary["track_6_legacy"] = {"total_pnl_inr": 250.0, "total_pnl_pct": 0.25}
        configured_notifier.notify_daily_recap(sample_summary)
        sent_ab = mock_send.call_args[0][0]
        assert "Legacy A:" in sent_ab
