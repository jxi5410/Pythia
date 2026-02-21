#!/usr/bin/env python3
"""Test Telegram bot connection for Pythia."""
import requests
import sys

BOT_TOKEN = "8384420812:AAFKzYH0mi7kqj4XHE1EhK6YrGDX3RMZRiw"
CHAT_ID = "8280876077"

def test_bot():
    """Send test message to verify bot works."""
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
