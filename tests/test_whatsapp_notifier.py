"""
Unit tests for TraderAI WhatsApp Real-Time Notification Engine.
Verifies message formatting, provider dispatching (CallMeBot, Webhook, Twilio),
phone number normalization, and error handling.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot.whatsapp_notifier import WhatsAppNotifier


def test_whatsapp_disabled_by_default():
    """Verify that when disabled, send_message returns False without making HTTP requests."""
    notifier = WhatsAppNotifier(enabled=False, phone="+919876543210", apikey="123456")
    with patch("requests.get") as mock_get:
        assert notifier.send_message("Test message") is False
        mock_get.assert_not_called()


def test_phone_normalization():
    """Verify that 10-digit Indian numbers automatically receive +91 prefix and formatting is stripped."""
    notifier = WhatsAppNotifier(enabled=False)
    assert notifier._normalize_phone("9876543210") == "+919876543210"
    assert notifier._normalize_phone("+91 98765-43210") == "+919876543210"
    assert notifier._normalize_phone("+1 (415) 555-2671") == "+14155552671"


@patch("requests.get")
def test_callmebot_success(mock_get):
    """Verify CallMeBot URL formatting and success handling."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Message queued successfully"
    mock_get.return_value = mock_resp

    notifier = WhatsAppNotifier(
        enabled=True,
        provider="callmebot",
        phone="+919876543210",
        apikey="SECRET123"
    )
    result = notifier.send_message("Hello from TraderAI!")
    assert result is True
    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert "api.callmebot.com/whatsapp.php" in called_url
    assert "phone=%2B919876543210" in called_url or "phone=+919876543210" in called_url
    assert "apikey=SECRET123" in called_url
    assert "Hello+from+TraderAI%21" in called_url or "Hello" in called_url


@patch("requests.get")
def test_callmebot_failure_response(mock_get):
    """Verify CallMeBot error handling when API returns error message."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ERROR: Invalid APIKey"
    mock_get.return_value = mock_resp

    notifier = WhatsAppNotifier(
        enabled=True,
        provider="callmebot",
        phone="+919876543210",
        apikey="WRONG_KEY"
    )
    assert notifier.send_message("Test") is False


@patch("requests.post")
def test_webhook_dispatch(mock_post):
    """Verify self-hosted open-source webhook dispatching."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    notifier = WhatsAppNotifier(
        enabled=True,
        provider="webhook",
        phone="+919876543210",
        webhook_url="https://whatsapp.internal.domain/send"
    )
    result = notifier.send_message("Webhook alert test")
    assert result is True
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://whatsapp.internal.domain/send"
    assert call_args[1]["json"]["number"] == "+919876543210"


def test_alert_formatters_generate_rich_messages():
    """Verify all actionable trading alert formatters execute and produce rich text."""
    notifier = WhatsAppNotifier(enabled=True, provider="callmebot", phone="+919876543210", apikey="test")

    with patch.object(notifier, "send_message", return_value=True) as mock_send:
        # 1. Breakout Fill
        assert notifier.notify_breakout_fill(
            ticker="UNIONBANK.NS",
            fill_price=209.70,
            target_price=234.80,
            stop_loss=201.30,
            shares=158,
            sector="Banking"
        ) is True
        msg1 = mock_send.call_args[0][0]
        assert "UNIONBANK" in msg1
        assert "₹209.70" in msg1
        assert "₹234.80" in msg1

        # 2. Breakeven Lock
        assert notifier.notify_breakeven_lock(
            ticker="IDFCFIRSTB.NS",
            entry_price=83.71,
            current_price=87.60,
            pnl_pct=4.65,
            new_stop_loss=83.96
        ) is True
        msg2 = mock_send.call_args[0][0]
        assert "BREAKEVEN LOCK" in msg2
        assert "IDFCFIRSTB" in msg2
        assert "+4.65%" in msg2

        # 3. Target Hit
        assert notifier.notify_target_hit(
            ticker="SIGNATURE.NS",
            entry_price=844.0,
            exit_price=945.0,
            pnl_rupees=3939.0,
            pnl_pct=11.97
        ) is True
        msg3 = mock_send.call_args[0][0]
        assert "TARGET HIT" in msg3
        assert "SIGNATURE" in msg3

        # 4. Velocity Kill
        assert notifier.notify_velocity_kill(
            ticker="DEEPAKFERT.NS",
            entry_price=1460.0,
            exit_price=1437.2,
            days_held=3,
            pnl_pct=-1.56,
            freed_capital_inr=31618.4
        ) is True
        msg4 = mock_send.call_args[0][0]
        assert "72-HOUR VELOCITY GATE" in msg4
        assert "DEEPAKFERT" in msg4
