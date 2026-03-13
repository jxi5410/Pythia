"""Global test configuration — disables rate limiter for all tests."""

import os

# Disable rate limiting during tests
os.environ["PYTHIA_TESTING"] = "1"
