"""voice-trader: voice-controlled trading execution with hard safety guarantees.

Public API (lightweight, no optional deps):

    from voice_trader import create_session, run_command
"""

from .api import *  # noqa: F401,F403

__version__ = "0.1.0"
