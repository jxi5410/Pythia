#!/usr/bin/env python3
"""Revoke Telegram bot token."""
import requests

BOT_TOKEN = "8384420812:AAFKzYH0mi7kqj4XHE1EhK6YrGDX3RMZRiw"

# Try to revoke by deleting webhook and getting new token
# Actually, the only way to revoke is via BotFather
# But we can at least stop the bot

url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
try:
    requests.get(url, timeout=5)
    print("Webhook deleted")
except:
    pass

print("\n⚠️  USER ACTION REQUIRED:")
print("1. Message @BotFather")
print("2. Send /revoke")
print("3. Select your bot (@pythia_alerts_bot)")
print("4. BotFather will generate a NEW token")
print("5. Never share/commit the new token")
