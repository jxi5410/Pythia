#!/usr/bin/env python3
"""Test Telegram bot connection for Pythia."""
import os
import requests
import sys

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def test_bot():
    """Send test message to verify bot works."""
    if not BOT_TOKEN or not CHAT_ID:
        print("Skipping live Telegram test: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set.")
        return True

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    message = """
🎯 <b>PYTHIA ALERTS — ACTIVE</b>

Bot configured successfully.
You will receive real-time trading signals here.

<b>Monitoring:</b> Polymarket, Kalshi
<b>Signals:</b> Probability spikes, volume anomalies, momentum
<b>Severity:</b> 🔴 CRITICAL | 🟠 HIGH | 🟡 MEDIUM | 🟢 LOW

Ready to detect alpha.
"""
    
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Bot test successful! Check your Telegram.")
        return True
    except Exception as e:
        print(f"❌ Bot test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_bot()
    sys.exit(0 if success else 1)
