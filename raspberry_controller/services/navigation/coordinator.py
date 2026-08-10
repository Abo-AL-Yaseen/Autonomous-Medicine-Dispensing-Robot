"""Event-driven intersection coordination with fail-closed navigation behavior."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..camera import ArucoCameraService
from ..mission_executor import (
    MissionExecutionState,
    MissionExecutor,
    MissionRouteUnavailableError,
)
from .route_planner import NavigationMapError, RouteDecision, UnknownMarkerError


INTERSECTION_EVENT_PREFIX = "EVENT|INTERSECTION|"
INTERSECTION_COMPLETE_PREFIX = "EVENT|INTERSECTION_COMPLETE|"
INTERSECTION_FAILED_PREFIX = "EVENT|INTERSECTION_FAILED|"


@dataclass(frozen=True)
class NavigationCoordinatorSettings:
    enabled: bool = False

    @classmethod
    def from_environment(cls) -> "NavigationCoordinatorSettings":
        value = os.getenv("NAVIGATION_AUTO_ENABLED", "false").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return cls(enabled=True)
        if value in {"0", "false", "no", "off"}:
            return cls(enabled=False)
        raise ValueError("NAVIGATION_AUTO_ENABLED must be a boolean")


class NavigationCoordinatorState(str, Enum):
    DISABLED = "DISABLED"
    WAITING_FOR_INTERSECTION = "WAITING_FOR_INTERSECTION"
    PROCESSING_INTERSECTION = "PROCESSING_INTERSECTION"
    COMMAND_SENT = "COMMAND_SENT"
    ARRIVED_AT_ROOM = "ARRIVED_AT_ROOM"
    ERROR = "ERROR"


class NavigationCoordinator:
    """Turn confirmed serial intersection events into one safe route action."""

    def __init__(
        self,
        *,
        settings: NavigationCoordinatorSettings,
        executor: MissionExecutor,
        camera_service: ArucoCameraService,
        next_serial_event: Callable[[float], str | None],
        intersection_left: Callable[[], str],
        intersection_right: Callable[[], str],
        intersection_straight: Callable[[], str],
        stop_line_follow: Callable[[], str],
    ) -> None:
        self._settings = settings
        self._executor = executor
        self._camera_service = camera_service
        self._next_serial_event = next_serial_event
        self._commands = {
            RouteDecision.LEFT: ("INTERSECTION_LEFT", intersection_left),
            RouteDecision.RIGHT: ("INTERSECTION_RIGHT", intersection_right),
            RouteDecision.STRAIGHT: (
                "INTERSECTION_STRAIGHT",
                intersection_straight,
            ),
        }
        self._stop_line_follow = stop_line_follow
        self._lock = threading.Lock()
        self._processing_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._armed = True
        self._state = (
            NavigationCoordinatorState.WAITING_FOR_INTERSECTION
            if settings.enabled
            else NavigationCoordinatorState.DISABLED
        )
        self._last_intersection_event: str | None = None
        self._last_marker_id: int | None = None
        self._last_node: str | None = None
        self._last_decision: str | None = None
        self._last_command: str | None = None
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._event_loop,
            name="navigation-event-coordinator",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None

    def process_serial_line(self, line: str) -> None:
        """Process one line already dispatched by the sole serial reader."""

        if line.startswith(INTERSECTION_COMPLETE_PREFIX):
            with self._lock:
                self._armed = True
                if self._state is NavigationCoordinatorState.COMMAND_SENT:
                    self._state = NavigationCoordinatorState.WAITING_FOR_INTERSECTION
                    self._last_error = None
            return

        if line.startswith(INTERSECTION_FAILED_PREFIX):
            with self._lock:
                self._last_intersection_event = line
            self._record_error("INTERSECTION_MANEUVER_FAILED")
            return

        if not line.startswith(INTERSECTION_EVENT_PREFIX):
            return

        if not self.enabled:
            with self._lock:
                self._last_intersection_event = line
                self._state = NavigationCoordinatorState.DISABLED
                self._last_error = "NAVIGATION_AUTO_DISABLED"
            return

        self._process_intersection(line, execute_command=True, enforce_debounce=True)

    def preview_test_intersection(self) -> dict[str, object]:
        """Evaluate a synthetic event without ever dispatching a command."""

        self._process_intersection(
            "EVENT|INTERSECTION|SOURCE=TEST",
            execute_command=False,
            enforce_debounce=False,
        )
        return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "state": self._state.value,
                "mission_id": self._executor.mission_id,
                "armed": self._armed,
                "last_intersection_event": self._last_intersection_event,
                "last_marker_id": self._last_marker_id,
                "last_node": self._last_node,
                "last_decision": self._last_decision,
                "last_command": self._last_command,
                "last_error": self._last_error,
            }

    def _event_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                line = self._next_serial_event(0.2)
            except Exception:
                self._record_error("SERIAL_EVENT_READ_FAILED")
                self._stop_event.wait(0.2)
                continue
            if line is not None:
                try:
                    self.process_serial_line(line)
                except Exception:
                    self._record_error("NAVIGATION_EVENT_PROCESSING_FAILED")

    def _process_intersection(
        self,
        event: str,
        *,
        execute_command: bool,
        enforce_debounce: bool,
    ) -> None:
        if not self._processing_lock.acquire(blocking=False):
            self._record_error("INTERSECTION_EVENT_ALREADY_PROCESSING")
            return

        try:
            with self._lock:
                self._last_intersection_event = event
                if enforce_debounce and not self._armed:
                    self._last_error = "DUPLICATE_INTERSECTION_EVENT"
                    return
                self._last_command = None
                self._last_error = None
                if enforce_debounce:
                    self._armed = False
                self._state = NavigationCoordinatorState.PROCESSING_INTERSECTION

            if self._executor.state is not MissionExecutionState.GOING_TO_ROOM:
                self._record_error("EXECUTOR_NOT_GOING_TO_ROOM")
                return

            detection = self._camera_service.detect()
            if not detection.camera_available:
                self._record_error("CAMERA_UNAVAILABLE")
                return
            if (
                not detection.detected
                or not detection.confirmed
                or detection.marker_id is None
            ):
                self._record_error("MARKER_NOT_CONFIRMED")
                return

            try:
                _, plan = self._executor.plan_route(detection.marker_id)
            except UnknownMarkerError:
                self._record_error("UNKNOWN_MARKER")
                return
            except MissionRouteUnavailableError:
                self._record_error("MISSION_ROUTE_UNAVAILABLE")
                return
            except NavigationMapError:
                self._record_error("NAVIGATION_MAP_INVALID")
                return
            except Exception:
                self._record_error("ROUTE_PLANNING_FAILED")
                return

            with self._lock:
                self._last_marker_id = detection.marker_id
                self._last_node = plan.current_node.name
                self._last_decision = plan.decision.value

            if plan.decision is RouteDecision.NO_ROUTE:
                self._record_error("NO_ROUTE")
                return

            if plan.decision is RouteDecision.ARRIVED:
                if not execute_command:
                    with self._lock:
                        self._state = NavigationCoordinatorState.DISABLED
                        self._last_error = "TEST_PREVIEW_ONLY"
                    return

                stop_error: str | None = None
                try:
                    self._stop_line_follow()
                except Exception:
                    stop_error = "LINE_FOLLOW_STOP_FAILED"
                self._executor.mark_arrived_at_room()
                with self._lock:
                    self._state = NavigationCoordinatorState.ARRIVED_AT_ROOM
                    self._last_error = stop_error
                return

            command = self._commands.get(plan.decision)
            if command is None:
                self._record_error("UNSUPPORTED_NAVIGATION_DECISION")
                return

            command_name, operation = command
            if not execute_command:
                with self._lock:
                    self._state = NavigationCoordinatorState.DISABLED
                    self._last_error = "TEST_PREVIEW_ONLY"
                return

            try:
                operation()
            except Exception:
                self._record_error("INTERSECTION_COMMAND_FAILED")
                return

            with self._lock:
                self._last_command = command_name
                self._state = NavigationCoordinatorState.COMMAND_SENT
                self._last_error = None
        finally:
            self._processing_lock.release()

    def _record_error(self, code: str) -> None:
        with self._lock:
            self._state = NavigationCoordinatorState.ERROR
            self._last_error = code
