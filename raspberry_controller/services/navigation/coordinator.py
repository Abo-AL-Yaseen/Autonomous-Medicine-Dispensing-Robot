"""Event-driven intersection coordination with fail-closed navigation behavior."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..camera import ArucoCameraService, FreshConfirmationSession
from ..mission_executor import (
    MissionExecutionState,
    MissionExecutor,
    MissionRouteUnavailableError,
)
from .route_planner import NavigationMapError, RouteDecision, UnknownMarkerError


INTERSECTION_EVENT_PREFIX = "EVENT|INTERSECTION|"
INTERSECTION_COMPLETE_PREFIX = "EVENT|INTERSECTION_COMPLETE|"
INTERSECTION_FAILED_PREFIX = "EVENT|INTERSECTION_FAILED|"
U_TURN_COMPLETE_PREFIX = "EVENT|U_TURN_COMPLETE|"
U_TURN_FAILED_PREFIX = "EVENT|U_TURN_FAILED"


@dataclass(frozen=True)
class NavigationCoordinatorSettings:
    enabled: bool = False
    arrived_home_observation_seconds: float = 1.0
    hand_wait_timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> "NavigationCoordinatorSettings":
        value = os.getenv("NAVIGATION_AUTO_ENABLED", "false").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            enabled = True
        elif value in {"0", "false", "no", "off"}:
            enabled = False
        else:
            raise ValueError("NAVIGATION_AUTO_ENABLED must be a boolean")
        try:
            observation_seconds = float(
                os.getenv("ARRIVED_HOME_OBSERVATION_SECONDS", "1.0")
            )
        except ValueError as exc:
            raise ValueError(
                "ARRIVED_HOME_OBSERVATION_SECONDS must be a number"
            ) from exc
        if observation_seconds < 0:
            raise ValueError(
                "ARRIVED_HOME_OBSERVATION_SECONDS must be non-negative"
            )
        try:
            hand_wait_timeout_seconds = float(
                os.getenv("HAND_WAIT_TIMEOUT_SECONDS", "30.0")
            )
        except ValueError as exc:
            raise ValueError("HAND_WAIT_TIMEOUT_SECONDS must be a number") from exc
        if hand_wait_timeout_seconds <= 0:
            raise ValueError("HAND_WAIT_TIMEOUT_SECONDS must be positive")
        return cls(
            enabled=enabled,
            arrived_home_observation_seconds=observation_seconds,
            hand_wait_timeout_seconds=hand_wait_timeout_seconds,
        )


class NavigationCoordinatorState(str, Enum):
    DISABLED = "DISABLED"
    WAITING_FOR_INTERSECTION = "WAITING_FOR_INTERSECTION"
    PROCESSING_INTERSECTION = "PROCESSING_INTERSECTION"
    COMMAND_SENT = "COMMAND_SENT"
    ARRIVED_AT_ROOM = "ARRIVED_AT_ROOM"
    WAITING_FOR_HAND = "WAITING_FOR_HAND"
    DISPENSING = "DISPENSING"
    RETURNING_HOME = "RETURNING_HOME"
    ARRIVED_HOME = "ARRIVED_HOME"
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
        show_medicine_workflow_status: Callable[[str], str] | None = None,
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
        self._show_medicine_workflow_status = (
            show_medicine_workflow_status or (lambda state: "")
        )
        self._lock = threading.Lock()
        self._processing_lock = threading.Lock()
        self._post_arrival_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._post_arrival_thread: threading.Thread | None = None
        self._post_arrival_mission_id: int | None = None
        self._home_finalization_thread: threading.Thread | None = None
        self._home_finalization_mission_id: int | None = None
        self._ignore_stale_events_while_idle = False
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
        self._expected_marker_id: int | None = None
        self._expected_mission_id: int | None = None
        self._last_marker_area: int | None = None
        self._last_second_marker_id: int | None = None
        self._last_second_marker_area: int | None = None
        self._last_area_ratio: float | None = None
        self._last_selection_ambiguous = False
        self._intersection_event_sequence: int | None = None
        self._first_detection_sequence_used: int | None = None
        self._confirmed_detection_sequences: tuple[int, ...] = ()

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
        post_arrival_thread = self._post_arrival_thread
        if (
            post_arrival_thread is not None
            and post_arrival_thread is not threading.current_thread()
        ):
            post_arrival_thread.join()
        self._post_arrival_thread = None
        home_finalization_thread = self._home_finalization_thread
        if (
            home_finalization_thread is not None
            and home_finalization_thread is not threading.current_thread()
        ):
            home_finalization_thread.join()
        self._home_finalization_thread = None

    def process_serial_line(self, line: str) -> None:
        """Process one line already dispatched by the sole serial reader."""

        # Arrival cleanup leaves the serial reader alive.  Ignore residual
        # completion/intersection lines until another mission actually starts,
        # so a late line from the prior mission cannot alter the clean state.
        with self._lock:
            ignore_stale_event = (
                self._ignore_stale_events_while_idle
                and self._executor.state
                in {
                    MissionExecutionState.IDLE,
                    MissionExecutionState.READY_FOR_EXECUTION,
                    MissionExecutionState.STARTING,
                }
            )
        if ignore_stale_event and self._is_intersection_event(line):
            return

        if not self.enabled and self._is_intersection_event(line):
            self._observe_disabled_event(line)
            return

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

        if line.startswith(U_TURN_COMPLETE_PREFIX):
            with self._lock:
                if self._executor.state is MissionExecutionState.RETURNING_HOME:
                    self._armed = True
                    self._state = NavigationCoordinatorState.RETURNING_HOME
                    self._last_error = None
            return

        if line.startswith(U_TURN_FAILED_PREFIX):
            with self._lock:
                self._last_intersection_event = line
            self._record_error("U_TURN_MANEUVER_FAILED")
            return

        if not line.startswith(INTERSECTION_EVENT_PREFIX):
            return

        self._process_intersection(line, execute_command=True, enforce_debounce=True)

    def begin_return_home(self) -> dict[str, object]:
        """Start one validated room U-turn and prepare return marker tracking."""

        with self._processing_lock:
            if self._executor.state not in {
                MissionExecutionState.ARRIVED_AT_ROOM,
                MissionExecutionState.DISPENSE_COMPLETED,
            }:
                return {
                    "success": False,
                    "result": "RETURN_NOT_ALLOWED",
                    "message": (
                        f"MissionExecutor is {self._executor.state.value}."
                    ),
                    "executor": self._executor.status(),
                }
            destination = self._executor.destination_node
            try:
                if destination is None:
                    raise MissionRouteUnavailableError(
                        "Mission destination context is unavailable."
                    )
                _, plan = self._executor.plan_return_route(destination.marker_id)
                if (
                    plan.decision is not RouteDecision.U_TURN
                    or plan.next_node is None
                ):
                    raise MissionRouteUnavailableError(
                        "Return route does not begin with U_TURN."
                    )
                expected_marker_id = self._executor.marker_for_node(
                    plan.next_node
                )
            except (MissionRouteUnavailableError, NavigationMapError) as exc:
                return {
                    "success": False,
                    "result": "RETURN_ROUTE_UNAVAILABLE",
                    "message": str(exc),
                    "executor": self._executor.status(),
                }

            # Disarm before sending U_TURN. Its asynchronous completion can
            # follow the ACK immediately, and must be allowed to re-arm us.
            with self._lock:
                self._armed = False
                self._expected_marker_id = expected_marker_id
                self._expected_mission_id = self._executor.mission_id
                self._last_command = None
                self._last_error = None
                self._state = NavigationCoordinatorState.RETURNING_HOME

            outcome = self._executor.start_return_home()
            if not outcome.success:
                with self._lock:
                    self._expected_marker_id = None
                    self._last_error = outcome.result.value
                    self._state = NavigationCoordinatorState.ERROR
                return {
                    **outcome.as_dict(),
                    "executor": self._executor.status(),
                }

            with self._lock:
                self._last_command = "U_TURN"
                self._last_error = None
            return {
                **outcome.as_dict(),
                "expected_marker_id": expected_marker_id,
                "executor": self._executor.status(),
            }

    def preview_test_intersection(self) -> dict[str, object]:
        """Evaluate a synthetic event without ever dispatching a command."""

        event = "EVENT|INTERSECTION|SOURCE=TEST"
        if not self.enabled:
            self._observe_disabled_event(event)
            return self.status()

        self._process_intersection(
            event,
            execute_command=False,
            enforce_debounce=False,
        )
        return self.status()

    @staticmethod
    def _is_intersection_event(line: str) -> bool:
        return line.startswith(
            (
                INTERSECTION_EVENT_PREFIX,
                INTERSECTION_COMPLETE_PREFIX,
                INTERSECTION_FAILED_PREFIX,
            )
        )

    def _observe_disabled_event(self, event: str) -> None:
        with self._lock:
            self._last_intersection_event = event
            self._last_marker_id = None
            self._last_node = None
            self._last_decision = None
            self._last_command = None
            self._last_error = None
            self._expected_marker_id = None
            self._expected_mission_id = None
            self._last_marker_area = None
            self._last_second_marker_id = None
            self._last_second_marker_area = None
            self._last_area_ratio = None
            self._last_selection_ambiguous = False
            self._intersection_event_sequence = None
            self._first_detection_sequence_used = None
            self._confirmed_detection_sequences = ()
            self._state = NavigationCoordinatorState.DISABLED

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
                "expected_marker_id": self._expected_marker_id,
                "last_marker_area": self._last_marker_area,
                "last_second_marker_id": self._last_second_marker_id,
                "last_second_marker_area": self._last_second_marker_area,
                "last_area_ratio": self._last_area_ratio,
                "last_selection_ambiguous": self._last_selection_ambiguous,
                "intersection_event_sequence": self._intersection_event_sequence,
                "first_detection_sequence_used": (
                    self._first_detection_sequence_used
                ),
                "confirmed_detection_sequences": list(
                    self._confirmed_detection_sequences
                ),
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

            executor_state = self._executor.state
            if executor_state not in {
                MissionExecutionState.GOING_TO_ROOM,
                MissionExecutionState.RETURNING_HOME,
            }:
                self._record_error("EXECUTOR_NOT_GOING_TO_ROOM")
                return

            with self._lock:
                self._ignore_stale_events_while_idle = False

            # Rooms 2 and 3 share the NODE_0 -> NODE_1 -> NODE_2 corridor.
            # After the ESP32 intersection event has put it in stopped
            # processing, start an atomic new camera confirmation session.
            # The map still determines the actual current node and direction.
            requires_post_stop_confirmation = (
                executor_state is MissionExecutionState.GOING_TO_ROOM
                and self._executor.room_id in {2, 3}
            )
            if requires_post_stop_confirmation:
                # Do not leave any pre-event marker as navigation evidence if
                # the fresh session fails before it yields a result.
                with self._lock:
                    self._last_marker_id = None
                    self._last_marker_area = None
                    self._last_second_marker_id = None
                    self._last_second_marker_area = None
                    self._last_area_ratio = None
                    self._last_selection_ambiguous = False
                    self._intersection_event_sequence = None
                    self._first_detection_sequence_used = None
                    self._confirmed_detection_sequences = ()

            mission_id = self._executor.mission_id
            with self._lock:
                if self._expected_mission_id != mission_id:
                    self._expected_marker_id = None
                    self._expected_mission_id = mission_id
                expected_marker_id = self._expected_marker_id

            fresh_session: FreshConfirmationSession | None = None
            if requires_post_stop_confirmation:
                fresh_session = (
                    self._camera_service.detect_from_new_confirmation_session(
                        expected_marker_id=expected_marker_id,
                    )
                )
                detection = fresh_session.detection
            else:
                detection = self._camera_service.detect(
                    expected_marker_id=expected_marker_id,
                )
            with self._lock:
                self._intersection_event_sequence = (
                    fresh_session.boundary_sequence
                    if fresh_session is not None
                    else None
                )
                self._first_detection_sequence_used = (
                    fresh_session.first_detection_sequence
                    if fresh_session is not None
                    else None
                )
                self._confirmed_detection_sequences = (
                    fresh_session.detection_sequences
                    if fresh_session is not None
                    else ()
                )
                self._last_marker_id = detection.marker_id
                self._last_marker_area = detection.area
                self._last_second_marker_id = detection.second_marker_id
                self._last_second_marker_area = detection.second_area
                self._last_area_ratio = detection.area_ratio
                self._last_selection_ambiguous = detection.ambiguous
            if not detection.camera_available:
                self._record_error("CAMERA_UNAVAILABLE")
                return
            if detection.ambiguous:
                self._record_error("AMBIGUOUS_MARKERS")
                return
            if detection.selection_error == "UNEXPECTED_MARKER":
                self._record_error("UNEXPECTED_MARKER")
                return
            if (
                not detection.detected
                or not detection.confirmed
                or detection.marker_id is None
            ):
                self._record_error("MARKER_NOT_CONFIRMED")
                return

            try:
                if executor_state is MissionExecutionState.RETURNING_HOME:
                    _, plan = self._executor.plan_return_route(detection.marker_id)
                else:
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
                if executor_state is MissionExecutionState.RETURNING_HOME:
                    self._executor.mark_arrived_home()
                else:
                    self._executor.mark_arrived_at_room()
                with self._lock:
                    self._expected_marker_id = None
                    self._state = (
                        NavigationCoordinatorState.ARRIVED_HOME
                        if executor_state is MissionExecutionState.RETURNING_HOME
                        else NavigationCoordinatorState.ARRIVED_AT_ROOM
                    )
                    self._last_error = stop_error
                if executor_state is MissionExecutionState.RETURNING_HOME:
                    self._start_home_finalization()
                if (
                    executor_state is MissionExecutionState.GOING_TO_ROOM
                    and stop_error is None
                ):
                    self._start_post_arrival_workflow()
                return

            command = self._commands.get(plan.decision)
            if command is None:
                self._record_error("UNSUPPORTED_NAVIGATION_DECISION")
                return

            command_name, operation = command
            if plan.next_node is None:
                self._record_error("NAVIGATION_MAP_INVALID")
                return
            try:
                next_marker_id = self._executor.marker_for_node(plan.next_node)
            except (MissionRouteUnavailableError, NavigationMapError):
                self._record_error("NAVIGATION_MAP_INVALID")
                return
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
                self._expected_marker_id = next_marker_id
                self._expected_mission_id = mission_id
                self._state = NavigationCoordinatorState.COMMAND_SENT
                self._last_error = None
        finally:
            self._processing_lock.release()

    def _record_error(self, code: str) -> None:
        with self._lock:
            self._state = NavigationCoordinatorState.ERROR
            self._last_error = code

    def _start_home_finalization(self) -> None:
        """Keep the confirmed home arrival observable, then release it."""

        mission_id = self._executor.mission_id
        with self._post_arrival_lock:
            if (
                mission_id is None
                or self._home_finalization_mission_id == mission_id
            ):
                return
            self._home_finalization_mission_id = mission_id
            self._home_finalization_thread = threading.Thread(
                target=self._finalize_arrived_home,
                name="mission-home-finalization",
                daemon=True,
            )
            self._home_finalization_thread.start()

    def _finalize_arrived_home(self) -> None:
        if self._stop_event.wait(self._settings.arrived_home_observation_seconds):
            return
        if not self._executor.finalize_arrived_home():
            with self._lock:
                self._state = NavigationCoordinatorState.ARRIVED_HOME
                self._last_error = self._executor.status()["last_error"]
            return

        with self._lock:
            self._armed = True
            self._expected_marker_id = None
            self._expected_mission_id = None
            self._last_command = None
            self._last_error = None
            # Keep last_marker_id/NODE_0/ARRIVED as the proof of physical
            # arrival while making the coordinator ready for the next route.
            self._state = (
                NavigationCoordinatorState.WAITING_FOR_INTERSECTION
                if self.enabled
                else NavigationCoordinatorState.DISABLED
            )
            self._ignore_stale_events_while_idle = True

    def _start_post_arrival_workflow(self) -> None:
        """Start one background workflow without blocking ESP32 event reads."""

        mission_id = self._executor.mission_id
        with self._post_arrival_lock:
            if mission_id is None or self._post_arrival_mission_id == mission_id:
                return
            self._post_arrival_mission_id = mission_id
            self._post_arrival_thread = threading.Thread(
                target=self._run_post_arrival_workflow,
                name="mission-post-arrival",
                daemon=True,
            )
            self._post_arrival_thread.start()

    def _run_post_arrival_workflow(self) -> None:
        """Wait for a hand, dispense once, then start the validated return."""

        with self._lock:
            self._state = NavigationCoordinatorState.WAITING_FOR_HAND
        try:
            self._show_medicine_workflow_status("HAND_WAITING")
        except Exception:
            self._record_error("LCD_STATUS_FAILED")
            return

        hand = self._executor.wait_for_hand_confirmation(
            self._settings.hand_wait_timeout_seconds
        )
        if not hand.success:
            try:
                self._show_medicine_workflow_status(
                    "NO_HAND" if hand.result.value == "HAND_TIMEOUT" else "DISPENSE_FAILED"
                )
            except Exception:
                pass
            self._record_error(hand.result.value)
            return

        try:
            self._show_medicine_workflow_status("HAND_DETECTED")
            self._show_medicine_workflow_status("DISPENSING")
        except Exception:
            self._record_error("LCD_STATUS_FAILED")
            return

        with self._lock:
            self._state = NavigationCoordinatorState.DISPENSING
        dispense = self._executor.dispense_at_room()
        if not dispense.success:
            try:
                self._show_medicine_workflow_status("DISPENSE_FAILED")
            except Exception:
                pass
            self._record_error(dispense.result.value)
            return

        try:
            self._show_medicine_workflow_status("MEDICINE_READY")
        except Exception:
            self._record_error("LCD_STATUS_FAILED")
            return

        returned = self.begin_return_home()
        if not returned.get("success"):
            self._record_error(str(returned.get("result", "RETURN_START_FAILED")))
