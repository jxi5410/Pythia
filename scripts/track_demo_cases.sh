#!/bin/bash
# Track Pythia spike detections and save demo cases
# Run: ./scripts/track_demo_cases.sh

LOG_FILE="logs/pythia_demo_run_$(date +%Y%m%d).log"
DEMO_FILE="demo_cases/spikes_$(date +%Y%m%d).jsonl"
SUMMARY_FILE="demo_cases/summary.md"

mkdir -p demo_cases

echo "🔍 Monitoring Pythia for spike detections..."
echo "Log: $LOG_FILE"
echo "Demo cases: $DEMO_FILE"
echo ""

# Monitor log for spike detections
tail -f "$LOG_FILE" | while read line; do
    # Look for spike indicators
    if echo "$line" | grep -qi "SPIKE\|detected\|attribution"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') | $line" | tee -a "$DEMO_FILE"
    fi
    
    # Look for errors
    if echo "$line" | grep -qi "ERROR\|failed"; then
        echo "⚠️  $(date '+%H:%M:%S') | $line"
    fi
    
    # Look for cycle completions
    if echo "$line" | grep -qi "Cycle.*completed\|No significant signals"; then
        echo "✓ $(date '+%H:%M:%S') | Cycle complete"
    fi
done
