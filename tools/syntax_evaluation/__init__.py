"""Bounded authored-syntax prototypes and evidence collection."""

from .evaluation import evaluate_corpus, validate_baseline_lock
from .limits import DEFAULT_LIMITS, ParserLimits, PrototypeError


SELECTED_SYNTAX = "jsonc"

__all__ = (
    "DEFAULT_LIMITS",
    "ParserLimits",
    "PrototypeError",
    "SELECTED_SYNTAX",
    "evaluate_corpus",
    "validate_baseline_lock",
)
