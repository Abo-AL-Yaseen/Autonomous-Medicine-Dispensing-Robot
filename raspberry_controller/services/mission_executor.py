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
MISSION_WATER_DISPENSE_MS = 4000
MISSION_PICKUP_WAIT_SECONDS = 30


class MissionExecutionState(str, Enum):
    IDLE = "IDLE"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    STARTING = "STARTING"
    GOING_TO_ROOM = "GOING_TO_ROOM"
    ARRIVED_AT_ROOM = "ARRIVED_AT_ROOM"
    WAITING_FOR_HAND = "WAITING_FOR_HAND"
    DISPENSING = "DISPENSING"
    DISPENSE_COMPLETED = "DISPENSE_COMPLETED"
    WATER_DISPENSING = "WATER_DISPENSING"
    WATER_DISPENSE_COMPLETED = "WATER_DISPENSE_COMPLETED"
    WAITING_FOR_PICKUP = "WAITING_FOR_PICKUP"
    RETURNING_HOME = "RETURNING_HOME"
    ARRIVED_HOME = "ARRIVED_HOME"
    FAILED = "FAILED"


class MissionStartResult(str, Enum):
    STARTED = "STARTED"
    U_TURN_STARTED = "U_TURN_STARTED"
    NO_READY_MISSION = "NO_READY_MISSION"
    HOME_NOT_CONFIRMED = "HOME_NOT_CONFIRMED"
    HOME_UTURN_FAILED = "HOME_UTURN_FAILED"
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


class MissionDispenseResult(str, Enum):
    DISPENSE_COMPLETED = "DISPENSE_COMPLETED"
    DISPENSE_NOT_ALLOWED = "DISPENSE_NOT_ALLOWED"
    DISPENSE_FAILED = "DISPENSE_FAILED"


class MissionWaterResult(str, Enum):
    WATER_DISPENSE_COMPLETED = "WATER_DISPENSE_COMPLETED"
    WATER_DISPENSE_NOT_ALLOWED = "WATER_DISPENSE_NOT_ALLOWED"
    WATER_DISPENSE_FAILED = "WATER_DISPENSE_FAILED"


class MissionHandResult(str, Enum):
    HAND_CONFIRMED = "HAND_CONFIRMED"
    HAND_NOT_ALLOWED = "HAND_NOT_ALLOWED"
    HAND_TIMEOUT = "HAND_TIMEOUT"
    HAND_WAIT_FAILED = "HAND_WAIT_FAILED"


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


@dataclass(frozen=True)
class MissionDispenseOutcome:
    result: MissionDispenseResult
    success: bool
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "result": self.result.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class MissionWaterOutcome:
    result: MissionWaterResult
    success: bool
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "result": self.result.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class MissionHandOutcome:
    result: MissionHandResult
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
        wait_for_hand: Callable[[float], bool] | None = None,
        dispense_medicine: Callable[[int, int], dict[str, int]] | None = None,
        dispense_water: Callable[[int], dict[str, int]] | None = None,
        get_water_level: Callable[[], dict[str, object]] | None = None,
        get_disk_status: Callable[[], dict[str, dict[str, bool | int]]] | None = None,
        mark_mission_in_progress: Callable[[ClaimedMission], None] | None = None,
        mark_mission_completed: Callable[[ClaimedMission], None] | None = None,
        load_navigation_map: Callable[[], PhysicalNavigationMap] | None = None,
        auto_execution_enabled: bool = False,
        require_home_readiness: bool = True,
    ) -> None:
        self._lock = threading.Lock()
        self._state = MissionExecutionState.IDLE
        self._mission: ClaimedMission | None = None
        self._last_error: str | None = None
        self._hardware_available = hardware_available
        self._start_line_follow = start_line_follow
        self._stop_line_follow = stop_line_follow
        self._u_turn = u_turn
        self._wait_for_hand = wait_for_hand
        self._dispense_medicine = dispense_medicine
        self._dispense_water = dispense_water
        self._get_water_level = get_water_level
        self._get_disk_status = get_disk_status
        self._mark_mission_in_progress = mark_mission_in_progress
        self._mark_mission_completed = mark_mission_completed
        self._load_navigation_map = load_navigation_map
        self._route_planner: LaravelRoutePlanner | None = None
        self._destination_node: PhysicalNode | None = None
        self._hand_confirmed = False
        self._pickup_seconds_remaining: int | None = None
        self._auto_execution_enabled = auto_execution_enabled
        self._require_home_readiness = require_home_readiness
        self._home_ready = not require_home_readiness
        self._home_readiness_error: str | None = (
            None if self._home_ready else MissionStartResult.HOME_NOT_CONFIRMED.value
        )

    @property
    def state(self) -> MissionExecutionState:
        with self._lock:
            return self._state

    @property
    def mission_id(self) -> int | None:
        with self._lock:
            return self._mission.id if self._mission else None

    @property
    def room_id(self) -> int | None:
        """Return the loaded target room without exposing mission mutation."""

        with self._lock:
            return self._mission.room_id if self._mission else None

    def set_home_readiness(self, ready: bool, *, error: str | None = None) -> None:
        """Record the coordinator's confirmed stationary HOME precondition."""

        with self._lock:
            self._home_ready = ready
            self._home_readiness_error = (
                None
                if ready
                else error or MissionStartResult.HOME_NOT_CONFIRMED.value
            )

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
            self._hand_confirmed = False
            self._pickup_seconds_remaining = None
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
        """Plan the retained mission's Laravel-defined route to HOME."""

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
            self._hand_confirmed = False

    def wait_for_hand_confirmation(self, timeout_seconds: float) -> MissionHandOutcome:
        """Wait once for the ESP32's debounced hand confirmation at the room."""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        with self._lock:
            if self._state is not MissionExecutionState.ARRIVED_AT_ROOM:
                return MissionHandOutcome(
                    MissionHandResult.HAND_NOT_ALLOWED,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
            self._state = MissionExecutionState.WAITING_FOR_HAND
            self._hand_confirmed = False
            self._last_error = None

        try:
            if self._wait_for_hand is None:
                raise RuntimeError("Hand wait operation is not configured")
            confirmed = self._wait_for_hand(timeout_seconds)
        except Exception as exc:
            message = f"HAND_WAIT_FAILED: {exc}"
            with self._lock:
                self._state = MissionExecutionState.FAILED
                self._last_error = message
            return MissionHandOutcome(MissionHandResult.HAND_WAIT_FAILED, False, message)

        if not confirmed:
            with self._lock:
                self._state = MissionExecutionState.FAILED
                self._last_error = MissionHandResult.HAND_TIMEOUT.value
            return MissionHandOutcome(
                MissionHandResult.HAND_TIMEOUT,
                False,
                MissionHandResult.HAND_TIMEOUT.value,
            )

        with self._lock:
            if self._state is not MissionExecutionState.WAITING_FOR_HAND:
                return MissionHandOutcome(
                    MissionHandResult.HAND_NOT_ALLOWED,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
            self._hand_confirmed = True
            self._last_error = None
        return MissionHandOutcome(MissionHandResult.HAND_CONFIRMED, True)

    def start_return_home(self) -> MissionReturnOutcome:
        """Start one existing U-turn only after the pickup countdown reaches zero."""

        with self._lock:
            if (
                self._state is not MissionExecutionState.WAITING_FOR_PICKUP
                or self._pickup_seconds_remaining != 0
            ):
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
                if (
                    self._state is not MissionExecutionState.WAITING_FOR_PICKUP
                    or self._pickup_seconds_remaining != 0
                ):
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

    def dispense_at_room(self) -> MissionDispenseOutcome:
        """Dispense every retained mission item once, validating each UNO summary."""

        with self._lock:
            if (
                self._state is not MissionExecutionState.WAITING_FOR_HAND
                or not self._hand_confirmed
            ):
                return MissionDispenseOutcome(
                    MissionDispenseResult.DISPENSE_NOT_ALLOWED,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
            mission = self._mission
            if mission is None:
                self._state = MissionExecutionState.FAILED
                self._last_error = "Mission context is unavailable."
                return MissionDispenseOutcome(
                    MissionDispenseResult.DISPENSE_FAILED,
                    False,
                    self._last_error,
                )
            items = mission.items
            if not items or any(
                item.dispenser_box not in (1, 2) or item.quantity <= 0
                for item in items
            ):
                self._state = MissionExecutionState.FAILED
                self._last_error = "Mission dispenser data is invalid."
                return MissionDispenseOutcome(
                    MissionDispenseResult.DISPENSE_FAILED,
                    False,
                    self._last_error,
                )
            self._state = MissionExecutionState.DISPENSING
            self._hand_confirmed = False
            self._last_error = None

        try:
            if self._get_disk_status is not None:
                disk_status = self._get_disk_status()
                for box_number in sorted({item.dispenser_box for item in items}):
                    disk = disk_status.get(f"disk{box_number}")
                    if not isinstance(disk, dict) or disk.get("calibrated") is not True:
                        raise RuntimeError(f"DISK_NOT_CALIBRATED|BOX={box_number}")
            if self._dispense_medicine is None:
                raise RuntimeError("Medicine dispense operation is not configured")
            for item in items:
                result = self._dispense_medicine(item.dispenser_box, item.quantity)
                confirmed = result.get("dispensed_pills")
                if (
                    result.get("box_number") != item.dispenser_box
                    or result.get("requested_pills") != item.quantity
                    or confirmed != item.quantity
                ):
                    raise RuntimeError(
                        "Medicine item failed: "
                        f"medicine_id={item.medicine_id} "
                        f"box={item.dispenser_box} "
                        f"requested={item.quantity} "
                        f"confirmed={confirmed!r}"
                    )
        except Exception as exc:
            message = f"DISPENSE_FAILED: {exc}"
            with self._lock:
                self._state = MissionExecutionState.FAILED
                self._last_error = message
            return MissionDispenseOutcome(
                MissionDispenseResult.DISPENSE_FAILED,
                False,
                message,
            )

        with self._lock:
            self._state = MissionExecutionState.DISPENSE_COMPLETED
            self._last_error = None
        return MissionDispenseOutcome(
            MissionDispenseResult.DISPENSE_COMPLETED,
            True,
        )

    def dispense_water_at_room(self) -> MissionWaterOutcome:
        """Run the fixed, mission-owned water dispense only after medicine."""

        with self._lock:
            if self._state is not MissionExecutionState.DISPENSE_COMPLETED:
                return MissionWaterOutcome(
                    MissionWaterResult.WATER_DISPENSE_NOT_ALLOWED,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
            self._state = MissionExecutionState.WATER_DISPENSING
            self._last_error = None

        try:
            if self._get_water_level is not None:
                level = self._get_water_level()
                level_status = level.get("status")
                if level_status == "EMPTY":
                    raise RuntimeError("WATER_EMPTY")
                if level_status == "SENSOR_ERROR":
                    raise RuntimeError("WATER_LEVEL_SENSOR_ERROR")
                if level_status not in {"OK", "LOW"}:
                    raise RuntimeError(
                        f"WATER_LEVEL_INVALID_STATUS: {level_status!r}"
                    )
            if self._dispense_water is None:
                raise RuntimeError("Water dispense operation is not configured")
            result = self._dispense_water(MISSION_WATER_DISPENSE_MS)
            if result.get("duration_ms") != MISSION_WATER_DISPENSE_MS:
                raise RuntimeError(
                    "Water dispense did not confirm the required 4000 ms duration"
                )
        except Exception as exc:
            message = f"WATER_DISPENSE_FAILED: {exc}"
            with self._lock:
                self._state = MissionExecutionState.FAILED
                self._last_error = message
            return MissionWaterOutcome(
                MissionWaterResult.WATER_DISPENSE_FAILED,
                False,
                message,
            )

        with self._lock:
            self._state = MissionExecutionState.WATER_DISPENSE_COMPLETED
            self._last_error = None
        return MissionWaterOutcome(
            MissionWaterResult.WATER_DISPENSE_COMPLETED,
            True,
        )

    def begin_pickup_wait(self, seconds: int = MISSION_PICKUP_WAIT_SECONDS) -> bool:
        """Expose the completed delivery while the patient picks it up."""

        if seconds <= 0:
            raise ValueError("pickup wait seconds must be positive")
        with self._lock:
            if self._state is not MissionExecutionState.WATER_DISPENSE_COMPLETED:
                return False
            self._state = MissionExecutionState.WAITING_FOR_PICKUP
            self._pickup_seconds_remaining = seconds
            self._last_error = None
            return True

    def update_pickup_wait(self, seconds_remaining: int) -> bool:
        """Record one coordinator-owned countdown tick without dispatching motion."""

        if seconds_remaining < 0:
            raise ValueError("pickup countdown cannot be negative")
        with self._lock:
            if self._state is not MissionExecutionState.WAITING_FOR_PICKUP:
                return False
            self._pickup_seconds_remaining = seconds_remaining
            return True

    def complete_pickup_wait(self) -> bool:
        """Confirm the zero tick while retaining the guarded pickup-wait state."""

        with self._lock:
            if (
                self._state is not MissionExecutionState.WAITING_FOR_PICKUP
                or self._pickup_seconds_remaining != 0
            ):
                return False
            return True

    def mark_arrived_home(self) -> None:
        """Record return arrival while retaining mission diagnostic context."""

        with self._lock:
            if self._state is not MissionExecutionState.RETURNING_HOME:
                raise MissionRouteUnavailableError(
                    "MissionExecutor is not returning home"
                )
            self._state = MissionExecutionState.ARRIVED_HOME

    def finalize_arrived_home(self) -> bool:
        """Complete the confirmed mission and release its runtime context.

        Arrival remains visible as ``ARRIVED_HOME`` until this method is
        called by the navigation coordinator after its observation interval.
        A Laravel completion failure deliberately retains the mission rather
        than allowing a second mission to be claimed over an in-progress one.
        """

        with self._lock:
            if self._state is not MissionExecutionState.ARRIVED_HOME:
                return False
            mission = self._mission
            if mission is None:
                self._state = MissionExecutionState.FAILED
                self._last_error = "Mission context is unavailable at home arrival."
                return False

        try:
            if self._mark_mission_completed is not None:
                self._mark_mission_completed(mission)
        except Exception as exc:
            with self._lock:
                if (
                    self._state is MissionExecutionState.ARRIVED_HOME
                    and self._mission == mission
                ):
                    self._last_error = f"Laravel mission completion failed: {exc}"
            return False

        with self._lock:
            if (
                self._state is not MissionExecutionState.ARRIVED_HOME
                or self._mission != mission
            ):
                return False
            self._mission = None
            self._route_planner = None
            self._destination_node = None
            self._pickup_seconds_remaining = None
            self._last_error = None
            self._state = MissionExecutionState.IDLE
        return True

    def start_ready_mission(self) -> MissionStartOutcome:
        """Perform READY -> outbound U-turn; completion starts line following."""

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

            if self._require_home_readiness and not self._home_ready:
                message = self._home_readiness_error or (
                    MissionStartResult.HOME_NOT_CONFIRMED.value
                )
                self._last_error = message
                return MissionStartOutcome(
                    MissionStartResult.HOME_NOT_CONFIRMED,
                    False,
                    message,
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

        # The production API always enables HOME readiness and waits for the
        # ESP32 U-turn completion event.  Keep the dependency-light executor
        # mode used by offline route tests as the historical line-follow
        # boundary; it has no coordinator to consume that event.
        if not self._require_home_readiness:
            return self.complete_start_u_turn()

        try:
            if self._u_turn is None:
                raise RuntimeError("U-turn operation is not configured")
            acknowledgement = self._u_turn()
            if acknowledgement != U_TURN_STARTED_ACK:
                raise RuntimeError(
                    f"Unexpected U-turn acknowledgement: {acknowledgement!r}"
                )
        except Exception as exc:
            message = self._stop_after_failure(
                f"HOME_UTURN_FAILED: {exc}",
            )
            return self._fail(MissionStartResult.HOME_UTURN_FAILED, message)

        return MissionStartOutcome(MissionStartResult.U_TURN_STARTED, True)

    def complete_start_u_turn(self) -> MissionStartOutcome:
        """Start outbound line following after the ESP32 confirms the U-turn."""

        with self._lock:
            if self._state is not MissionExecutionState.STARTING:
                return MissionStartOutcome(
                    MissionStartResult.EXECUTOR_BUSY,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
            mission = self._mission

        if mission is None:
            return self._fail(
                MissionStartResult.INVALID_MISSION,
                "Claimed mission data is missing.",
            )

        try:
            if self._start_line_follow is None:
                raise RuntimeError("Line-follow start operation is not configured")
            acknowledgement = self._start_line_follow()
            if acknowledgement != LINE_FOLLOW_STARTED_ACK:
                raise RuntimeError(
                    f"Unexpected line-follow acknowledgement: {acknowledgement!r}"
                )
        except Exception as exc:
            message = self._stop_after_failure(f"Line-follow start failed: {exc}")
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

    def fail_start_u_turn(self) -> MissionStartOutcome:
        """Fail a pending outbound start when ESP32 reports U-turn failure."""

        with self._lock:
            if self._state is not MissionExecutionState.STARTING:
                return MissionStartOutcome(
                    MissionStartResult.EXECUTOR_BUSY,
                    False,
                    f"MissionExecutor is {self._state.value}.",
                )
        message = self._stop_after_failure(MissionStartResult.HOME_UTURN_FAILED.value)
        return self._fail(MissionStartResult.HOME_UTURN_FAILED, message)

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
                "pickup_seconds_remaining": self._pickup_seconds_remaining,
                "last_error": self._last_error,
                "auto_execution_enabled": self._auto_execution_enabled,
                "home_ready": self._home_ready,
                "home_readiness_error": self._home_readiness_error,
            }

    @staticmethod
    def _validate_mission(mission: ClaimedMission | None) -> str | None:
        if mission is None:
            return "Claimed mission data is missing."
        if not mission.room_number or not mission.room_number.strip():
            return "Claimed mission room_number is missing."
        if not mission.items:
            return "Claimed mission has no medicine items."
        if any(
            item.dispenser_box not in (1, 2) or item.quantity <= 0
            for item in mission.items
        ):
            return "Claimed mission medicine item is invalid."
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
