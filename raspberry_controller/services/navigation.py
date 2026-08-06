"""Service layer facade for the robot’s navigation graph.

This module re-exports the navigation graph service so application code can use
an application-level service boundary without reaching into the database layer.
"""

from __future__ import annotations

from ..navigation.graph import NavigationGraph

__all__ = ["NavigationGraph"]
