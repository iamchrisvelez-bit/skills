"""Brainiac — an overseer AI agent that plans, decides, delegates, renders and learns."""

from .config import Config
from .memory import MemoryStore
from .overseer import Brainiac

__all__ = ["Brainiac", "Config", "MemoryStore"]
__version__ = "1.0.0"
