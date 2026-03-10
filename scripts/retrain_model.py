#!/usr/bin/env python3
"""
Pythia Model Retraining — Run weekly to update the heterogeneous effects model.

Usage:
    python scripts/retrain_model.py
    python scripts/retrain_model.py --db data/pythia_live.db

Cron setup (every Monday at 6am):
    0 6 * * 1  cd ~/Pythia && python scripts/retrain_model.py >> data/retrain.log 2>&1
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.database import PythiaDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("retrain")


def main():
    parser = argparse.ArgumentParser(description="Retrain Pythia heterogeneous effects model")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "pythia_live.db"))
    args = parser.parse_args()

    db = PythiaDB(args.db)
    logger.info("Retraining started at %s", datetime.utcnow().isoformat())

    # Check data availability
    try:
        spikes = db.get_spike_events(min_magnitude=0.02, limit=1000)
        n_spikes = len(spikes)
        logger.info("Spike events in DB: %d", n_spikes)

        if n_spikes < 30:
            logger.warning("Insufficient data (%d spikes, need 30+). Run backfill_spikes.py first.", n_spikes)
            return
    except Exception as e:
        logger.error("Failed to query spike events: %s", e)
        return

    # Train model
    try:
        from core.heterogeneous_effects import train_heterogeneous_model, get_model_insights
        result = train_heterogeneous_model(db, n_estimators=200, save=True)

        if result.get("error"):
            logger.error("Training failed: %s", result["error"])
            return

        logger.info("Training complete:")
        logger.info("  Samples: %d", result.get("n_samples", 0))
        logger.info("  ATE: %.4f [%.4f, %.4f]",
                     result.get("ate", 0),
                     result.get("ate_ci_lower", 0),
                     result.get("ate_ci_upper", 0))

        # Log per-category effects
        for cat, eff in result.get("category_effects", {}).items():
            logger.info("  %s: effect=%.4f (n=%d)", cat, eff["mean_effect"], eff["n_samples"])

    except ImportError:
        logger.error("heterogeneous_effects module not available")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
