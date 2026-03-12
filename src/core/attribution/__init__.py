"""Deprecated transitional attribution package. Prefer core.bace."""

from .interfaces import AttributionEngine, AttributionResult
from .orchestrator import AttributionOrchestrator

__all__ = ["AttributionEngine", "AttributionResult", "AttributionOrchestrator"]
