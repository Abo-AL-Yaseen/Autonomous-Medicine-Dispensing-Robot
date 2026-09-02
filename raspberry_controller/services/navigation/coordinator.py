"""Event-driven intersection coordination with fail-closed navigation behavior."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..camera import ArucoCameraService, FreshConfirmationSession
from ..mission_executor import (
    LINE_FOLLOW_STARTED_ACK,
    MANUAL_RECOVERY_TIMEOUT_SECONDS,
    MISSION_PICKUP_WAIT_SECONDS,
    MissionExecutionState,
    MissionExecutor,
    MissionStartResult,
    MissionRouteUnavailableError,
)
from .route_planner import (
    NavigationMapError,
    PhysicalNavigationMap,
    RouteDecision,
    UnknownMarkerError,
)


INTERSECTION_EVENT_PREFIX = "EVENT|INTERSECTION|"
INTERSECTION_COMPLETE_PREFIX = "EVENT|INTERSECTION_COMPLETE|"
INTERSECTION_FAILED_PREFIX = "EVENT|INTERSECTION_FAILED|"
U_TURN_COMPLETE_PREFIX = "EVENT|U_TURN_COMPLETE|"
U_TURN_FAILED_PREFIX = "EVENT|U_TURN_FAILED"
LINE_LOST_PREFIX = "EVENT|LINE_LOST|"
U_TURN_FAILURE_DIAGNOSTIC_PREFIX = "UTURN|FAILURE="


@dataclass(frozen=True)
class NavigationCoordinatorSettings:
    enabled: bool = False
    arrived_home_observation_seconds: float = 1.0
    hand_wait_timeout_seconds: float = 30.0
    pickup_wait_seconds: int = MISSION_PICKUP_WAIT_SECONDS
    manual_recovery_timeout_seconds: float = MANUAL_RECOVERY_TIMEOUT_SECONDS

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
        try:
            manual_recovery_timeout_seconds = float(
                os.getenv(
                    "MANUAL_RECOVERY_TIMEOUT_SECONDS",
                    str(MANUAL_RECOVERY_TIMEOUT_SECONDS),
                )
            )
        except ValueError as exc:
            raise ValueError(
                "MANUAL_RECOVERY_TIMEOUT_SECONDS must be a number"
            ) from exc
        if manual_recovery_timeout_seconds <= 0:
            raise ValueError(
                "MANUAL_RECOVERY_TIMEOUT_SECONDS must be positive"
            )
        return cls(
            enabled=enabled,
            arrived_home_observation_seconds=observation_seconds,
            hand_wait_timeout_seconds=hand_wait_timeout_seconds,
            manual_recovery_timeout_seconds=manual_recovery_timeout_seconds,
        )


class NavigationCoordinatorState(str, Enum):
    DISABLED = "DISABLED"
    WAITING_FOR_INTERSECTION = "WAITING_FOR_INTERSECTION"
    PROCESSING_INTERSECTION = "PROCESSING_INTERSECTION"
    COMMAND_SENT = "COMMAND_SENT"
    ARRIVED_AT_ROOM = "ARRIVED_AT_ROOM"
    WAITING_FOR_HAND = "WAITING_FOR_HAND"
    DISPENSING = "DISPENSING"
    WATER_DISPENSING = "WATER_DISPENSING"
    WAITING_FOR_PICKUP = "WAITING_FOR_PICKUP"
    RETURNING_HOME = "RETURNING_HOME"
    WAITING_FOR_MANUAL_RECOVERY = "WAITING_FOR_MANUAL_RECOVERY"
    ARRIVED_HOME = "ARRIVED_HOME"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ManualRecoveryRouteContext:
    """Coordinator fields preserved across one bounded manual intervention."""

    generation: int
    previous_state: NavigationCoordinatorState
    armed: bool
    expected_marker_id: int | None
    expected_mission_id: int | None
    last_command: str | None
    completed_maneuver_checkpoint: bool


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
        show_pickup_countdown: Callable[[int], str] | None = None,
        wait_for_pickup_tick: Callable[[float], bool] | None = None,
        load_navigation_map: Callable[[], PhysicalNavigationMap] | None = None,
        home_line_position_is_valid: Callable[[], bool] | None = None,
        prepare_manual_recovery_resume: (
            Callable[[], tuple[bool, str, str | None]] | None
        ) = None,
        emergency_stop: Callable[[], str] | None = None,
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
        self._show_pickup_countdown = show_pickup_countdown or (lambda seconds: "")
        self._load_navigation_map = load_navigation_map
        self._home_line_position_is_valid = home_line_position_is_valid
        self._prepare_manual_recovery_resume = prepare_manual_recovery_resume
        self._emergency_stop = emergency_stop
        self._lock = threading.Lock()
        self._processing_lock = threading.Lock()
        self._post_arrival_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wait_for_pickup_tick = wait_for_pickup_tick or self._stop_event.wait
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
        self._home_ready = False
        self._home_marker_id: int | None = None
        self._home_line_position_valid = False
        self._home_readiness_error = "HOME_NOT_CONFIRMED"
        self._manual_recovery_context: ManualRecoveryRouteContext | None = None
        self._last_manual_recovery_resume_mission_id: int | None = None
        self._pending_u_turn_failure_reason: str | None = None

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
        if self._executor.state is MissionExecutionState.WAITING_FOR_MANUAL_RECOVERY:
            self.cancel_manual_recovery(reason="MANUAL_RECOVERY_CANCELLED")
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

        if self._executor.state is MissionExecutionState.WAITING_FOR_MANUAL_RECOVERY:
            # The sole reader keeps draining serial data while manual recovery
            # is active. Navigation lines from the failed checkpoint are stale
            # and must never re-arm or advance the preserved route.
            if self._is_navigation_event(line):
                return

        if line.startswith(U_TURN_FAILURE_DIAGNOSTIC_PREFIX):
            if self._executor.state in {
                MissionExecutionState.STARTING,
                MissionExecutionState.GOING_TO_ROOM,
                MissionExecutionState.RETURNING_HOME,
            }:
                with self._lock:
                    self._pending_u_turn_failure_reason = line.removeprefix(
                        U_TURN_FAILURE_DIAGNOSTIC_PREFIX
                    )
            return

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

        if line.startswith(LINE_LOST_PREFIX):
            with self._lock:
                self._last_intersection_event = line
            self._begin_manual_recovery("LINE_LOST", maneuver_failed=False)
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
            self._begin_manual_recovery(
                "INTERSECTION_MANEUVER_FAILED",
                maneuver_failed=True,
            )
            return

        if line.startswith(U_TURN_COMPLETE_PREFIX):
            with self._lock:
                self._pending_u_turn_failure_reason = None
            if self._executor.state is MissionExecutionState.STARTING:
                outcome = self._executor.complete_start_u_turn()
                with self._lock:
                    if outcome.success:
                        self._armed = True
                        self._state = NavigationCoordinatorState.WAITING_FOR_INTERSECTION
                        self._last_error = None
                    else:
                        self._armed = False
                        self._expected_marker_id = None
                        self._state = NavigationCoordinatorState.ERROR
                        self._last_error = outcome.result.value
                return
            with self._lock:
                if self._executor.state is MissionExecutionState.RETURNING_HOME:
                    self._armed = True
                    self._state = NavigationCoordinatorState.RETURNING_HOME
                    self._last_error = None
            return

        if line.startswith(U_TURN_FAILED_PREFIX):
            with self._lock:
                self._last_intersection_event = line
                detail = self._pending_u_turn_failure_reason
                self._pending_u_turn_failure_reason = None
            reason = "U_TURN_MANEUVER_FAILED"
            if detail:
                reason = f"{reason}|FAILURE={detail}"
            self._begin_manual_recovery(reason, maneuver_failed=True)
            return

        if not line.startswith(INTERSECTION_EVENT_PREFIX):
            return

        self._process_intersection(line, execute_command=True, enforce_debounce=True)

    def confirm_home_readiness(self) -> dict[str, object]:
        """Confirm the stationary HOME marker and the ESP32 line-stop state."""

        try:
            if self._load_navigation_map is None:
                raise NavigationMapError("Laravel navigation map loader is unavailable")
            home_node = self._load_navigation_map().node_named("HOME")
            if home_node is None or home_node.node_type != "home":
                raise NavigationMapError("Laravel map has no dedicated HOME node")
            detection = self._camera_service.detect(
                expected_marker_id=home_node.marker_id,
            )
            marker_confirmed = (
                detection.confirmed
                and detection.marker_id == home_node.marker_id
                and detection.node_name == home_node.name
            )
            line_position_valid = bool(
                self._home_line_position_is_valid
                and self._home_line_position_is_valid()
            )
        except Exception:
            return self._set_home_readiness(
                False,
                marker_id=None,
                line_position_valid=False,
                error="HOME_NOT_CONFIRMED",
            )

        with self._lock:
            self._last_marker_id = detection.marker_id
            self._last_node = home_node.name if marker_confirmed else None
            self._last_marker_area = detection.area
            self._last_second_marker_id = detection.second_marker_id
            self._last_second_marker_area = detection.second_area
            self._last_area_ratio = detection.area_ratio
            self._last_selection_ambiguous = detection.ambiguous

        if not marker_confirmed:
            return self._set_home_readiness(
                False,
                marker_id=home_node.marker_id,
                line_position_valid=line_position_valid,
                error="HOME_NOT_CONFIRMED",
            )
        if not line_position_valid:
            return self._set_home_readiness(
                False,
                marker_id=home_node.marker_id,
                line_position_valid=False,
                error="HOME_LINE_POSITION_NOT_CONFIRMED",
            )
        return self._set_home_readiness(
            True,
            marker_id=home_node.marker_id,
            line_position_valid=True,
            error=None,
        )

    def begin_outbound_from_home(self) -> dict[str, object]:
        """Validate HOME, start one U-turn, then await its completion event."""

        with self._processing_lock:
            if self._executor.state is not MissionExecutionState.READY_FOR_EXECUTION:
                outcome = self._executor.start_ready_mission()
                return {
                    **outcome.as_dict(),
                    "executor": self._executor.status(),
                }

            readiness = self.confirm_home_readiness()
            if not readiness["success"]:
                return {
                    "success": False,
                    "result": "HOME_NOT_CONFIRMED",
                    "message": readiness["error"],
                    "executor": self._executor.status(),
                    "home": readiness,
                }

            if self._state is NavigationCoordinatorState.ERROR:
                return {
                    "success": False,
                    "result": "NAVIGATION_NOT_READY",
                    "message": self._last_error,
                    "executor": self._executor.status(),
                    "home": readiness,
                }

            try:
                home_marker_id = int(readiness["marker_id"])
                _, plan = self._executor.plan_route(home_marker_id)
                if plan.decision is not RouteDecision.STRAIGHT or plan.next_node is None:
                    raise MissionRouteUnavailableError(
                        "Outbound HOME route does not begin with STRAIGHT."
                    )
                expected_marker_id = self._executor.marker_for_node(plan.next_node)
            except (MissionRouteUnavailableError, NavigationMapError) as exc:
                return {
                    "success": False,
                    "result": "OUTBOUND_ROUTE_UNAVAILABLE",
                    "message": str(exc),
                    "executor": self._executor.status(),
                    "home": readiness,
                }

            with self._lock:
                self._armed = False
                self._expected_marker_id = expected_marker_id
                self._expected_mission_id = self._executor.mission_id
                self._last_command = None
                self._last_error = None
                self._state = NavigationCoordinatorState.COMMAND_SENT

            outcome = self._executor.start_ready_mission()
            if not outcome.success:
                water_preflight_rejected = outcome.result in {
                    MissionStartResult.WATER_EMPTY,
                    MissionStartResult.WATER_LEVEL_SENSOR_ERROR,
                }
                with self._lock:
                    self._armed = water_preflight_rejected
                    self._expected_marker_id = None
                    self._expected_mission_id = None
                    self._state = (
                        NavigationCoordinatorState.WAITING_FOR_INTERSECTION
                        if water_preflight_rejected and self.enabled
                        else NavigationCoordinatorState.DISABLED
                        if water_preflight_rejected
                        else NavigationCoordinatorState.ERROR
                    )
                    self._last_error = outcome.result.value
                return {
                    **outcome.as_dict(),
                    "executor": self._executor.status(),
                    "home": readiness,
                }

            with self._lock:
                self._last_command = "U_TURN"
            return {
                **outcome.as_dict(),
                "expected_marker_id": expected_marker_id,
                "executor": self._executor.status(),
                "home": readiness,
            }

    def begin_return_home(self) -> dict[str, object]:
        """Start one validated room U-turn and prepare return marker tracking."""

        with self._processing_lock:
            executor_status = self._executor.status()
            if (
                self._executor.state is not MissionExecutionState.WAITING_FOR_PICKUP
                or executor_status["pickup_seconds_remaining"] != 0
            ):
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

    @staticmethod
    def _is_navigation_event(line: str) -> bool:
        return line.startswith(
            (
                INTERSECTION_EVENT_PREFIX,
                INTERSECTION_COMPLETE_PREFIX,
                INTERSECTION_FAILED_PREFIX,
                U_TURN_COMPLETE_PREFIX,
                U_TURN_FAILED_PREFIX,
                LINE_LOST_PREFIX,
                U_TURN_FAILURE_DIAGNOSTIC_PREFIX,
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

    def _set_home_readiness(
        self,
        ready: bool,
        *,
        marker_id: int | None,
        line_position_valid: bool,
        error: str | None,
    ) -> dict[str, object]:
        self._executor.set_home_readiness(ready, error=error)
        with self._lock:
            self._home_ready = ready
            self._home_marker_id = marker_id
            self._home_line_position_valid = line_position_valid
            self._home_readiness_error = error
            if ready and self._state is NavigationCoordinatorState.ERROR:
                self._state = (
                    NavigationCoordinatorState.WAITING_FOR_INTERSECTION
                    if self.enabled
                    else NavigationCoordinatorState.DISABLED
                )
                self._last_error = None
            elif not ready:
                self._last_error = error
                self._state = NavigationCoordinatorState.ERROR
            return {
                "success": ready,
                "ready": ready,
                "marker_id": marker_id,
                "line_position_valid": line_position_valid,
                "error": error,
            }

    def _begin_manual_recovery(
        self,
        reason: str,
        *,
        maneuver_failed: bool,
    ) -> None:
        """Stop autonomous motion and preserve one recoverable route checkpoint."""

        with self._processing_lock:
            executor_state = self._executor.state
            if executor_state not in {
                MissionExecutionState.STARTING,
                MissionExecutionState.GOING_TO_ROOM,
                MissionExecutionState.RETURNING_HOME,
            }:
                return

            with self._lock:
                previous_coordinator_state = self._state
                previous_armed = self._armed
                expected_marker_id = self._expected_marker_id
                expected_mission_id = self._expected_mission_id
                last_command = self._last_command

            try:
                acknowledgement = self._stop_line_follow()
                if acknowledgement != "ACK|LINE_FOLLOW_STOPPED":
                    raise RuntimeError(
                        "Unexpected line-follow stop acknowledgement: "
                        f"{acknowledgement!r}"
                    )
            except Exception as exc:
                failure = f"{reason}|SAFE_STOP_FAILED={exc}"
                self._executor.fail_active_navigation(failure)
                self._record_error(failure)
                return

            snapshot = self._executor.begin_manual_recovery(
                reason,
                timeout_seconds=self._settings.manual_recovery_timeout_seconds,
            )
            if snapshot is None:
                self._record_error(reason)
                return

            context = ManualRecoveryRouteContext(
                generation=snapshot.generation,
                previous_state=previous_coordinator_state,
                armed=previous_armed,
                expected_marker_id=expected_marker_id,
                expected_mission_id=expected_mission_id,
                last_command=last_command,
                completed_maneuver_checkpoint=(
                    maneuver_failed
                    or previous_coordinator_state
                    is NavigationCoordinatorState.COMMAND_SENT
                    or (
                        executor_state is MissionExecutionState.STARTING
                        and last_command == "U_TURN"
                    )
                ),
            )
            with self._lock:
                self._manual_recovery_context = context
                self._last_manual_recovery_resume_mission_id = None
                self._pending_u_turn_failure_reason = None
                self._armed = False
                self._state = NavigationCoordinatorState.WAITING_FOR_MANUAL_RECOVERY
                self._last_error = reason

    def execute_manual_recovery_drive(
        self,
        operation: Callable[[], str],
    ) -> tuple[bool, str | None]:
        """Serialize one manual drive request against resume, timeout, and STOP."""

        with self._processing_lock:
            snapshot = self._executor.manual_recovery_snapshot()
            if snapshot is None:
                return False, None
            if self._executor.manual_recovery_expired(snapshot.generation):
                self._fail_manual_recovery_locked("MANUAL_RECOVERY_TIMEOUT")
                return False, None
            try:
                return True, operation()
            except Exception:
                self._fail_manual_recovery_locked(
                    "MANUAL_RECOVERY_HARDWARE_FAILED"
                )
                raise

    def resume_manual_recovery(self) -> dict[str, object]:
        """Validate the line and continue the same saved route exactly once."""

        with self._processing_lock:
            snapshot = self._executor.manual_recovery_snapshot()
            mission_id = self._executor.mission_id
            if snapshot is None:
                if (
                    mission_id is not None
                    and mission_id == self._last_manual_recovery_resume_mission_id
                ):
                    return {
                        "success": True,
                        "result": "MANUAL_RECOVERY_RESUMED",
                        "already_resumed": True,
                        "executor": self._executor.status(),
                    }
                return {
                    "success": False,
                    "result": "MANUAL_RECOVERY_NOT_ACTIVE",
                    "code": "MANUAL_RECOVERY_NOT_ACTIVE",
                    "message": "Manual recovery is not active.",
                    "executor": self._executor.status(),
                }

            if self._executor.manual_recovery_expired(snapshot.generation):
                self._fail_manual_recovery_locked("MANUAL_RECOVERY_TIMEOUT")
                return {
                    "success": False,
                    "result": "MANUAL_RECOVERY_TIMEOUT",
                    "code": "MANUAL_RECOVERY_TIMEOUT",
                    "message": "The manual recovery window has expired.",
                    "executor": self._executor.status(),
                }

            if self._prepare_manual_recovery_resume is None:
                raise RuntimeError("Manual recovery line validation is not configured")
            try:
                line_is_valid, line_reading, acknowledgement = (
                    self._prepare_manual_recovery_resume()
                )
            except Exception:
                self._fail_manual_recovery_locked(
                    "MANUAL_RECOVERY_RESUME_FAILED"
                )
                raise
            if not line_is_valid:
                return {
                    "success": False,
                    "result": "LINE_NOT_DETECTED_FOR_RESUME",
                    "code": "LINE_NOT_DETECTED_FOR_RESUME",
                    "message": "A safe line position was not detected on O2, O3, or O4.",
                    "line_reading": line_reading,
                    "executor": self._executor.status(),
                }
            if acknowledgement != LINE_FOLLOW_STARTED_ACK:
                self._fail_manual_recovery_locked(
                    "MANUAL_RECOVERY_RESUME_FAILED"
                )
                raise RuntimeError(
                    "Unexpected line-follow start acknowledgement: "
                    f"{acknowledgement!r}"
                )

            if snapshot.previous_state is MissionExecutionState.STARTING:
                restored_state = self._executor.restore_manual_recovery(
                    snapshot.generation
                )
                if restored_state is not MissionExecutionState.STARTING:
                    self._fail_manual_recovery_locked("MANUAL_RECOVERY_TIMEOUT")
                    return {
                        "success": False,
                        "result": "MANUAL_RECOVERY_TIMEOUT",
                        "code": "MANUAL_RECOVERY_TIMEOUT",
                        "message": "The manual recovery window has expired.",
                        "executor": self._executor.status(),
                    }
                outcome = self._executor.complete_start_u_turn(
                    line_follow_already_started=True
                )
                if not outcome.success:
                    with self._lock:
                        self._manual_recovery_context = None
                        self._state = NavigationCoordinatorState.ERROR
                        self._last_error = outcome.result.value
                    return {
                        **outcome.as_dict(),
                        "executor": self._executor.status(),
                    }
            else:
                restored_state = self._executor.restore_manual_recovery(
                    snapshot.generation
                )
                if restored_state is None:
                    self._fail_manual_recovery_locked("MANUAL_RECOVERY_TIMEOUT")
                    return {
                        "success": False,
                        "result": "MANUAL_RECOVERY_TIMEOUT",
                        "code": "MANUAL_RECOVERY_TIMEOUT",
                        "message": "The manual recovery window has expired.",
                        "executor": self._executor.status(),
                    }

            with self._lock:
                context = self._manual_recovery_context
                if context is not None and context.generation == snapshot.generation:
                    self._expected_marker_id = context.expected_marker_id
                    self._expected_mission_id = context.expected_mission_id
                    self._last_command = context.last_command
                    if context.completed_maneuver_checkpoint:
                        self._armed = True
                        self._state = (
                            NavigationCoordinatorState.RETURNING_HOME
                            if snapshot.previous_state
                            is MissionExecutionState.RETURNING_HOME
                            else NavigationCoordinatorState.WAITING_FOR_INTERSECTION
                        )
                    else:
                        self._armed = context.armed
                        self._state = context.previous_state
                    self._manual_recovery_context = None
                self._last_error = None
                self._last_manual_recovery_resume_mission_id = mission_id

            return {
                "success": True,
                "result": "MANUAL_RECOVERY_RESUMED",
                "already_resumed": False,
                "line_reading": line_reading,
                "previous_state": snapshot.previous_state.value,
                "checkpoint_completed": bool(
                    context and context.completed_maneuver_checkpoint
                ),
                "executor": self._executor.status(),
            }

    def cancel_manual_recovery(
        self,
        *,
        reason: str = "MANUAL_RECOVERY_CANCELLED",
    ) -> dict[str, object]:
        """Stop motion and apply the retained-mission failure path once."""

        with self._processing_lock:
            applied, response = self._fail_manual_recovery_locked(reason)
            return {
                "success": applied,
                "result": reason if applied else "MANUAL_RECOVERY_NOT_ACTIVE",
                "response": response,
                "executor": self._executor.status(),
            }

    def check_manual_recovery_timeout(self) -> bool:
        """Apply an elapsed monotonic deadline without blocking the event loop."""

        if not self._processing_lock.acquire(blocking=False):
            return False
        try:
            snapshot = self._executor.manual_recovery_snapshot()
            if (
                snapshot is None
                or not self._executor.manual_recovery_expired(snapshot.generation)
            ):
                return False
            applied, _ = self._fail_manual_recovery_locked(
                "MANUAL_RECOVERY_TIMEOUT"
            )
            return applied
        finally:
            self._processing_lock.release()

    def _fail_manual_recovery_locked(
        self,
        reason: str,
    ) -> tuple[bool, str | None]:
        snapshot = self._executor.manual_recovery_snapshot()
        if snapshot is None:
            return False, None

        response: str | None = None
        stop_error: Exception | None = None
        try:
            if self._emergency_stop is None:
                raise RuntimeError("Emergency stop operation is not configured")
            response = self._emergency_stop()
            if response != "ACK|STOP":
                raise RuntimeError(
                    f"Unexpected emergency stop acknowledgement: {response!r}"
                )
        except Exception as exc:
            stop_error = exc

        final_reason = (
            reason
            if stop_error is None
            else f"{reason}|SAFE_STOP_FAILED={stop_error}"
        )
        applied = self._executor.fail_manual_recovery(
            snapshot.generation,
            final_reason,
        )
        if applied:
            with self._lock:
                self._manual_recovery_context = None
                self._armed = False
                self._state = NavigationCoordinatorState.ERROR
                self._last_error = final_reason
        return applied, response

    def status(self) -> dict[str, object]:
        with self._lock:
            recovery_context = self._manual_recovery_context
            result: dict[str, object] = {
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
                "home_ready": self._home_ready,
                "home_marker_id": self._home_marker_id,
                "home_line_position_valid": self._home_line_position_valid,
                "home_readiness_error": self._home_readiness_error,
            }
            if recovery_context is not None:
                result["manual_recovery_checkpoint_completed"] = (
                    recovery_context.completed_maneuver_checkpoint
                )
            return result

    def _event_loop(self) -> None:
        while not self._stop_event.is_set():
            self.check_manual_recovery_timeout()
            try:
                line = self._next_serial_event(0.2)
            except Exception:
                if self._executor.state is MissionExecutionState.WAITING_FOR_MANUAL_RECOVERY:
                    with self._processing_lock:
                        self._fail_manual_recovery_locked(
                            "SERIAL_EVENT_READ_FAILED"
                        )
                else:
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
            self._executor.set_home_readiness(True)
            self._home_ready = True
            self._home_marker_id = self._last_marker_id
            self._home_line_position_valid = True
            self._home_readiness_error = None
            self._armed = True
            self._expected_marker_id = None
            self._expected_mission_id = None
            self._last_command = None
            self._last_error = None
            # Keep last_marker_id/HOME/ARRIVED as the proof of physical
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
        """Run the one guarded hand, medicine, water, pickup, return workflow."""

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
            self._show_medicine_workflow_status("WATER_DISPENSING")
        except Exception:
            self._record_error("LCD_STATUS_FAILED")
            return

        with self._lock:
            self._state = NavigationCoordinatorState.WATER_DISPENSING
        water = self._executor.dispense_water_at_room()
        if not water.success:
            try:
                self._show_medicine_workflow_status("DISPENSE_FAILED")
            except Exception:
                pass
            self._record_error(water.result.value)
            return

        try:
            self._show_medicine_workflow_status("MEDICINE_READY")
        except Exception:
            self._record_error("LCD_STATUS_FAILED")
            return

        if not self._executor.begin_pickup_wait(self._settings.pickup_wait_seconds):
            self._record_error("PICKUP_WAIT_NOT_ALLOWED")
            return
        with self._lock:
            self._state = NavigationCoordinatorState.WAITING_FOR_PICKUP

        for seconds_remaining in range(self._settings.pickup_wait_seconds, -1, -1):
            if not self._executor.update_pickup_wait(seconds_remaining):
                self._record_error("PICKUP_WAIT_NOT_ALLOWED")
                return
            try:
                self._show_pickup_countdown(seconds_remaining)
            except Exception:
                self._record_error("LCD_STATUS_FAILED")
                return
            if seconds_remaining > 0 and self._wait_for_pickup_tick(1.0):
                return

        if not self._executor.complete_pickup_wait():
            self._record_error("PICKUP_WAIT_NOT_ALLOWED")
            return

        returned = self.begin_return_home()
        if not returned.get("success"):
            self._record_error(str(returned.get("result", "RETURN_START_FAILED")))
