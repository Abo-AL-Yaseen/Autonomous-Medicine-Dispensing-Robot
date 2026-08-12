"""Controlled first execution step for one claimed Laravel mission."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .laravel_api_client import ClaimedMission
from .navigation import (
    LaravelRoutePlanner,
    NavigationMapError,
    PhysicalNavigationMap,
    PhysicalNode,
    RouteDecision,
    RoutePlan,
)


LINE_FOLLOW_STARTED_ACK = "ACK|LINE_FOLLOW_STARTED"
LINE_FOLLOW_STOPPED_ACK = "ACK|LINE_FOLLOW_STOPPED"
U_TURN_STARTED_ACK = "ACK|U_TURN_STARTED"


class MissionExecutionState(str, Enum):
    IDLE = "IDLE"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    STARTING = "STARTING"
    GOING_TO_ROOM = "GOING_TO_ROOM"
    ARRIVED_AT_ROOM = "ARRIVED_AT_ROOM"
    RETURNING_HOME = "RETURNING_HOME"
    ARRIVED_HOME = "ARRIVED_HOME"
    FAILED = "FAILED"


class MissionStartResult(str, Enum):
    STARTED = "STARTED"
    NO_READY_MISSION = "NO_READY_MISSION"
    HARDWARE_UNAVAILABLE = "HARDWARE_UNAVAILABLE"
    EXECUTOR_BUSY = "EXECUTOR_BUSY"
    INVALID_MISSION = "INVALID_MISSION"
    LINE_FOLLOW_START_FAILED = "LINE_FOLLOW_START_FAILED"
    MISSION_STATUS_UPDATE_FAILED = "MISSION_STATUS_UPDATE_FAILED"


class MissionReturnResult(str, Enum):
    RETURN_STARTED = "RETURN_STARTED"
    RETURN_NOT_ALLOWED = "RETURN_NOT_ALLOWED"
    HARDWARE_UNAVAILABLE = "HARDWARE_UNAVAILABLE"
    RETURN_ROUTE_UNAVAILABLE = "RETURN_ROUTE_UNAVAILABLE"
    U_TURN_START_FAILED = "U_TURN_START_FAILED"


class MissionRouteUnavailableError(RuntimeError):
    """No accepted mission or Laravel map is available for route preview."""


@dataclass(frozen=True)
class MissionStartOutcome:
    result: MissionStartResult
    success: bool
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "result": self.result.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class MissionReturnOutcome:
    result: MissionReturnResult
    success: bool
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "result": self.result.value,
            "message": self.message,
        }


class MissionExecutor:
    """Start line following, then durably mark the claimed mission in progress."""

    def __init__(
        self,
        *,
        hardware_available: Callable[[], bool] = lambda: False,
        start_line_follow: Callable[[], str] | None = None,
        stop_line_follow: Callable[[], str] | None = None,
        u_turn: Callable[[], str] | None = None,
        mark_mission_in_progress: Callable[[ClaimedMission], None] | None = None,
        load_navigation_map: Callable[[], PhysicalNavigationMap] | None = None,
        auto_execution_enabled: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._state = MissionExecutionState.IDLE
        self._mission: ClaimedMission | None = None
        self._last_error: str | None = None
        self._hardware_available = hardware_available
        self._start_line_follow = start_line_follow
        self._stop_line_follow = stop_line_follow
        self._u_turn = u_turn
        self._mark_mission_in_progress = mark_mission_in_progress
        self._load_navigation_map = load_navigation_map
        self._route_planner: LaravelRoutePlanner | None = None
        self._destination_node: PhysicalNode | None = None
        self._auto_execution_enabled = auto_execution_enabled

    @property
    def state(self) -> MissionExecutionState:
        with self._lock:
            return self._state

    @property
    def mission_id(self) -> int | None:
        with self._lock:
            return self._mission.id if self._mission else None

    def accept(self, mission: ClaimedMission) -> bool:
        """Transition IDLE to READY exactly once for the accepted mission."""

        with self._lock:
            if self._state is not MissionExecutionState.IDLE:
                if (
                    self._state is MissionExecutionState.READY_FOR_EXECUTION
                    and self._mission
                    and self._mission.id == mission.id
                ):
                    return False
                raise RuntimeError("MissionExecutor is already holding a mission")

        route_planner: LaravelRoutePlanner | None = None
        destination_node: PhysicalNode | None = None
        if self._load_navigation_map is not None:
            navigation_map = self._load_navigation_map()
            route_planner = LaravelRoutePlanner(navigation_map)
            destination_node = route_planner.destination_for_room(mission.room_id)

        with self._lock:
            if self._state is not MissionExecutionState.IDLE:
                if (
                    self._state is MissionExecutionState.READY_FOR_EXECUTION
                    and self._mission
                    and self._mission.id == mission.id
                ):
                    return False
                raise RuntimeError("MissionExecutor is already holding a mission")
            self._mission = mission
            self._route_planner = route_planner
            self._destination_node = destination_node
            self._last_error = None
            self._state = MissionExecutionState.READY_FOR_EXECUTION
            return True

    def plan_route(self, marker_id: int) -> tuple[ClaimedMission, RoutePlan]:
        """Preview a Laravel-backed route without changing state or hardware."""

        with self._lock:
            mission = self._mission
            route_planner = self._route_planner

        if mission is None:
            raise MissionRouteUnavailableError("No mission is loaded")
        if route_planner is None:
            raise MissionRouteUnavailableError(
                "No Laravel navigation map is loaded for this mission"
            )

        return mission, route_planner.plan(marker_id, mission.room_id)

    def plan_return_route(self, marker_id: int) -> tuple[ClaimedMission, RoutePlan]:
        """Plan the retained mission's Laravel-defined route to NODE_0."""

        with self._lock:
            mission = self._mission
            route_planner = self._route_planner

        if mission is None:
            raise MissionRouteUnavailableError("No mission is loaded")
        if route_planner is None:
            raise MissionRouteUnavailableError(
                "No Laravel navigation map is loaded for this mission"
            )

        return mission, route_planner.plan_return(marker_id, mission.room_id)

    def marker_for_node(self, node_name: str) -> int:
        """Resolve a route node through the loaded Laravel map snapshot."""

        with self._lock:
            route_planner = self._route_planner
        if route_planner is None:
            raise MissionRouteUnavailableError(
                "No Laravel navigation map is loaded for this mission"
            )
        node = route_planner.navigation_map.node_named(node_name)
        if node is None:
            raise NavigationMapError(
                f"Node {node_name} is not present in Laravel's map"
            )
        return node.marker_id

    @property
    def destination_node(self) -> PhysicalNode | None:
        with self._lock:
            return self._destination_node

    def mark_arrived_at_room(self) -> None:
        """Record physical arrival without completing or releasing the mission."""

        with self._lock:
            if self._state is not MissionExecutionState.GOING_TO_ROOM:
                raise MissionRouteUnavailableError(
                    "MissionExecutor is not going to a room"
                )
            self._state = MissionExecutionState.ARRIVED_AT_ROOM

    def start_return_home(self) -> MissionReturnOutcome:
        """Validate ARRIVED_AT_ROOM and start exactly one existing U-turn."""

        with self._lock:
            if self._state is not MissionExecutionState.ARRIVED_AT_ROOM:
                return MissionReturnOutcome(
                    MissionReturnResult.RETURN_NOT_ALLOWED,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
            mission = self._mission
            destination_node = self._destination_node
            try:
                hardware_is_available = self._hardware_available()
            except Exception:
                hardware_is_available = False
            if not hardware_is_available:
                self._last_error = "Robot hardware is unavailable."
                return MissionReturnOutcome(
                    MissionReturnResult.HARDWARE_UNAVAILABLE,
                    False,
                    self._last_error,
                )

        if mission is None or destination_node is None:
            return MissionReturnOutcome(
                MissionReturnResult.RETURN_ROUTE_UNAVAILABLE,
                False,
                "Mission destination context is unavailable.",
            )

        try:
            if self._u_turn is None:
                raise RuntimeError("U-turn operation is not configured")
            with self._lock:
                if self._state is not MissionExecutionState.ARRIVED_AT_ROOM:
                    return MissionReturnOutcome(
                        MissionReturnResult.RETURN_NOT_ALLOWED,
                        False,
                        f"MissionExecutor is {self._state.value}.",
                    )
                # Claim the return transition before hardware I/O so a second
                # request cannot dispatch another U-turn concurrently.
                self._state = MissionExecutionState.RETURNING_HOME
                self._last_error = None
            acknowledgement = self._u_turn()
            if acknowledgement != U_TURN_STARTED_ACK:
                raise RuntimeError(
                    f"Unexpected U-turn acknowledgement: {acknowledgement!r}"
                )
        except Exception as exc:
            message = self._stop_after_failure(f"U-turn start failed: {exc}")
            with self._lock:
                self._state = MissionExecutionState.FAILED
                self._last_error = message
            return MissionReturnOutcome(
                MissionReturnResult.U_TURN_START_FAILED,
                False,
                message,
            )

        return MissionReturnOutcome(MissionReturnResult.RETURN_STARTED, True)

    def mark_arrived_home(self) -> None:
        """Record return arrival while retaining mission diagnostic context."""

        with self._lock:
            if self._state is not MissionExecutionState.RETURNING_HOME:
                raise MissionRouteUnavailableError(
                    "MissionExecutor is not returning home"
                )
            self._state = MissionExecutionState.ARRIVED_HOME

    def start_ready_mission(self) -> MissionStartOutcome:
        """Perform only READY -> line follow -> in_progress -> GOING_TO_ROOM."""

        with self._lock:
            if self._state is MissionExecutionState.IDLE:
                return MissionStartOutcome(
                    MissionStartResult.NO_READY_MISSION,
                    False,
                    "No mission is ready for execution.",
                )
            if self._state is not MissionExecutionState.READY_FOR_EXECUTION:
                return MissionStartOutcome(
                    MissionStartResult.EXECUTOR_BUSY,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )

            mission = self._mission
            validation_error = self._validate_mission(mission)
            if validation_error is not None:
                self._state = MissionExecutionState.FAILED
                self._last_error = validation_error
                return MissionStartOutcome(
                    MissionStartResult.INVALID_MISSION,
                    False,
                    validation_error,
                )

            try:
                hardware_is_available = self._hardware_available()
            except Exception:
                hardware_is_available = False
            if not hardware_is_available:
                self._last_error = "Robot hardware is unavailable."
                return MissionStartOutcome(
                    MissionStartResult.HARDWARE_UNAVAILABLE,
                    False,
                    self._last_error,
                )

            self._state = MissionExecutionState.STARTING
            self._last_error = None

        assert mission is not None

        try:
            if self._start_line_follow is None:
                raise RuntimeError("Line-follow start operation is not configured")
            acknowledgement = self._start_line_follow()
            if acknowledgement != LINE_FOLLOW_STARTED_ACK:
                raise RuntimeError(
                    f"Unexpected line-follow acknowledgement: {acknowledgement!r}"
                )
        except Exception as exc:
            message = self._stop_after_failure(
                f"Line-follow start failed: {exc}",
            )
            return self._fail(MissionStartResult.LINE_FOLLOW_START_FAILED, message)

        try:
            if self._mark_mission_in_progress is None:
                raise RuntimeError("Laravel status update is not configured")
            self._mark_mission_in_progress(mission)
        except Exception as exc:
            message = self._stop_after_failure(
                f"Laravel mission status update failed: {exc}",
            )
            return self._fail(
                MissionStartResult.MISSION_STATUS_UPDATE_FAILED,
                message,
            )

        with self._lock:
            self._state = MissionExecutionState.GOING_TO_ROOM
            self._last_error = None

        return MissionStartOutcome(MissionStartResult.STARTED, True)

    def status(self) -> dict[str, object]:
        with self._lock:
            mission = self._mission
            return {
                "state": self._state.value,
                "mission_id": mission.id if mission else None,
                "room_id": mission.room_id if mission else None,
                "room_number": mission.room_number if mission else None,
                "target_room": mission.room_id if mission else None,
                "medicine_id": mission.medicine_id if mission else None,
                "dispenser_box": mission.dispenser_box if mission else None,
                "quantity": mission.quantity if mission else None,
                "last_error": self._last_error,
                "auto_execution_enabled": self._auto_execution_enabled,
            }

    @staticmethod
    def _validate_mission(mission: ClaimedMission | None) -> str | None:
        if mission is None:
            return "Claimed mission data is missing."
        if not mission.room_number or not mission.room_number.strip():
            return "Claimed mission room_number is missing."
        if mission.dispenser_box not in (1, 2):
            return "Claimed mission dispenser_box is invalid."
        if not mission.schedule_claimed_at:
            return "Claimed mission schedule_claimed_at is missing."
        return None

    def _stop_after_failure(self, primary_error: str) -> str:
        try:
            if self._stop_line_follow is None:
                raise RuntimeError("Line-follow stop operation is not configured")
            acknowledgement = self._stop_line_follow()
            if acknowledgement != LINE_FOLLOW_STOPPED_ACK:
                raise RuntimeError(
                    f"Unexpected line-follow stop acknowledgement: {acknowledgement!r}"
                )
        except Exception as stop_error:
            return f"{primary_error} Safe stop also failed: {stop_error}"
        return primary_error

    def _fail(
        self,
        result: MissionStartResult,
        message: str,
    ) -> MissionStartOutcome:
        with self._lock:
            self._state = MissionExecutionState.FAILED
            self._last_error = message
        return MissionStartOutcome(result, False, message)
