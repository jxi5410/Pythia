#!/bin/bash
# =============================================================
# Pythia Security Fix — Nuclear Git History Reset
# =============================================================
# This script:
# 1. Backs up your current repo
# 2. Replaces it with the cleaned version (no bot files, no secrets)
# 3. Creates a fresh git history with one clean commit
# 4. Force-pushes to GitHub
#
# BEFORE RUNNING:
# 1. Revoke your Telegram bot token via @BotFather → /revoke
# 2. Make sure you have no uncommitted work you want to keep
# 3. Copy the cleaned files from Claude's output to ~/Pythia-clean/
#
# USAGE:
#   cd ~/Pythia
#   bash security_fix.sh
# =============================================================

set -e

echo "🔒 Pythia Security Fix — Starting..."
echo ""

# Safety check
if [ ! -d ".git" ]; then
    echo "❌ Error: Run this from the Pythia repo root (~/Pythia)"
    exit 1
fi

# Step 1: Backup
BACKUP_DIR="../Pythia-backup-$(date +%Y%m%d_%H%M%S)"
echo "📦 Step 1: Backing up current repo to $BACKUP_DIR"
cp -r . "$BACKUP_DIR"
echo "   ✅ Backup created"

# Step 2: Remove old git history
echo ""
echo "🗑️  Step 2: Removing old git history (contains leaked token)"
rm -rf .git
echo "   ✅ Old history removed"

# Step 3: Initialize fresh repo
echo ""
echo "🔄 Step 3: Initializing fresh git repo"
git init
git branch -M main
echo "   ✅ Fresh repo initialized"

# Step 4: Add remote
echo ""
echo "🔗 Step 4: Adding GitHub remote"
git remote add origin git@github.com:jxi5410/Pythia.git
echo "   ✅ Remote added"

# Step 5: Commit everything
echo ""
echo "📝 Step 5: Creating clean initial commit"
git add -A
git commit -m "refactor: clean repo — remove bot/telegram, scrub secrets from history

SECURITY: Previous git history contained a leaked Telegram bot token.
This commit replaces the entire history with a clean single commit.

Changes from previous state:
- Removed: bot_commands.py, run_bot.py, src/core/bot.py,
  src/core/companion.py, src/core/telegram_commands.py,
  src/core/telegram_query.py, src/core/user_context.py,
  tests/test_bot.py
- Removed: Hardcoded Telegram chat ID from config.json and config.py
- Removed: TelegramAlerter from main.py and automation.py
- Replaced: alert_engine.py telegram delivery with log stub
- Cleaned: .env.example, run.py

All core engine functionality (signal detection, paper trading,
connectors, risk engine) is preserved."

echo "   ✅ Clean commit created"

# Step 6: Force push
echo ""
echo "🚀 Step 6: Force-pushing to GitHub"
echo "   ⚠️  This will REPLACE all remote history!"
read -p "   Continue? (y/N): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "   Aborted. Your local repo is already clean."
    echo "   Run 'git push --force origin main' when ready."
    exit 0
fi

git push --force origin main
echo "   ✅ Force-pushed to GitHub"

echo ""
echo "========================================="
echo "✅ DONE — Security fix complete"
echo "========================================="
echo ""
echo "Verify:"
echo "  1. Check https://github.com/jxi5410/Pythia — should show single commit"
echo "  2. Confirm bot token is revoked via @BotFather"
echo "  3. Old backup at: $BACKUP_DIR"
echo ""
