"""Application-level navigation service boundary.

This module keeps the business-facing navigation service separated from the
hardware controller and raw graph implementation.
"""

from __future__ import annotations

from ..navigation.engine import NavigationService

__all__ = ["NavigationService"]
