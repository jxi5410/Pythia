#!/usr/bin/env python3
"""
Pythia Live Pipeline — Entry point.

Usage:
  python3 run_pipeline.py                  # Run continuously
  python3 run_pipeline.py --once           # Single cycle
  python3 run_pipeline.py --dry-run        # No LLM calls or alerts
  python3 run_pipeline.py --once --dry-run # Single dry-run cycle (testing)
"""
import argparse
import logging
import os
import signal
import sys

# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pythia_live.pipeline import Pipeline


def main():
    parser = argparse.ArgumentParser(description="Pythia Live Pipeline")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and detect only, no LLM attribution")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    parser.add_argument("--db", default="data/pythia_live.db", help="Database path")
    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Env vars
    os.environ.setdefault("NEWSAPI_KEY", "5d5fa368d38e4a1ab2b37a7666c5148c")

    # Ensure data dir exists
    os.makedirs(os.path.dirname(args.db) or "data", exist_ok=True)

    pipeline = Pipeline(db_path=args.db, dry_run=args.dry_run)

    # Graceful shutdown
    def handle_signal(sig, frame):
        logging.info("Shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.once:
        alerts = pipeline.run_cycle()
        logging.info("Cycle complete. %d alerts generated.", len(alerts))
    else:
        pipeline.run_loop(interval=args.interval)


if __name__ == "__main__":
    main()
