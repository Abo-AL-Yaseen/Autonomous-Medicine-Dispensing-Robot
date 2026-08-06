"""Navigation service package.

All robot navigation logic, floor-map coordination, path planning, and
movement orchestration should be implemented here instead of in the hardware
controller layer.
"""

from ...navigation.graph import NavigationGraph

__all__ = ["NavigationGraph"]
