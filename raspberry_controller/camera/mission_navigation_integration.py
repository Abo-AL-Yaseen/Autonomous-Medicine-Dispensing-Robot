"""Camera-to-navigation integration for active robot missions.

The camera implementation supplies detected ArUco IDs to ``process_marker``
or ``run``.  This module intentionally owns no camera, serial, navigation, or
mission business logic; it only coordinates the existing components.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from threading import Event, Lock
from typing import Protocol

from ..hardware_controller import RobotHardwareController
from ..navigation.engine import NavigationDecision, NavigationService
from ..services.mission_service import MissionService


logger = logging.getLogger(__name__)


class MarkerSource(Protocol):
    """Blocking source of detected ArUco marker IDs."""

    def __call__(self) -> int | None:
        """Return the next marker ID, or ``None`` when no marker is visible."""


class MissionNavigationIntegration:
    """Dispatch navigation decisions for newly detected ArUco markers.

    A marker is processed once until a different marker is detected.  The
    camera layer may call :meth:`process_marker` for every video frame safely.
    """

    def __init__(
        self,
        hardware_controller: RobotHardwareController,
        mission_service: MissionService,
        navigation_service: NavigationService,
        *,
        hardware_lock: Lock | None = None,
    ) -> None:
        self._hardware_controller = hardware_controller
        self._mission_service = mission_service
        self._navigation_service = navigation_service
        self._hardware_lock = hardware_lock or Lock()
        self._last_marker_id: int | None = None

    def process_marker(self, marker_id: int) -> str | None:
        """Handle one detected marker and return its navigation decision.

        ``None`` means the marker was ignored because it is a repeated frame or
        because there is no active mission.
        """

        mission = self._mission_service.get_active_mission()
        if mission is None:
            self._last_marker_id = None
            return None

        if marker_id == self._last_marker_id:
            return None
        self._last_marker_id = marker_id

        logger.info("Detected Marker: %s", marker_id)
        direction = self._navigation_service.next_direction(marker_id, mission.room_id)
        logger.info("Navigation Decision: %s", direction)

        if direction == NavigationDecision.STRAIGHT.value:
            self._move(self._hardware_controller.forward)
        elif direction == NavigationDecision.LEFT.value:
            self._move(self._hardware_controller.turn_left)
        elif direction == NavigationDecision.RIGHT.value:
            self._move(self._hardware_controller.turn_right)
        elif direction == NavigationDecision.ARRIVED.value:
            self._move(self._hardware_controller.stop)
            self._mission_service.complete_mission(mission.id)
            logger.info("Mission %s completed at marker %s", mission.id, marker_id)
        elif direction == NavigationDecision.UNKNOWN.value:
            logger.warning("Unknown navigation decision at marker %s; robot will not move", marker_id)
        else:
            logger.warning("Unsupported navigation decision %r; robot will not move", direction)

        return direction

    def run(self, next_marker: MarkerSource, stop_event: Event) -> None:
        """Continuously process camera detections while a mission is active.

        ``next_marker`` should block until the camera produces a detection or
        no-marker frame.  The loop ends when requested or once no mission is
        active (including immediately after arrival).
        """

        while not stop_event.is_set():
            if self._mission_service.get_active_mission() is None:
                return

            marker_id = next_marker()
            if marker_id is not None:
                self.process_marker(marker_id)

    def process_markers(self, marker_ids: Iterable[int]) -> None:
        """Convenience adapter for an existing camera marker-ID iterator."""

        for marker_id in marker_ids:
            if self._mission_service.get_active_mission() is None:
                return
            self.process_marker(marker_id)

    def _move(self, operation: Callable[[], str]) -> None:
        """Serialize access to the existing hardware controller."""

        with self._hardware_lock:
            operation()
