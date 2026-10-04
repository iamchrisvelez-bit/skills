"""Jarvis-readiness evaluation suite for Brainiac. See PROTOCOLS.md."""

from .protocols import CAPABILITIES, PROTOCOLS, TIERS, probe
from .runner import gap_report, run_protocol, run_suite, scorecard

__all__ = ["CAPABILITIES", "PROTOCOLS", "TIERS", "gap_report", "probe", "run_protocol", "run_suite", "scorecard"]
