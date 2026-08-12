"""Software-only safety tests for event-driven intersection navigation."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from unittest.mock import Mock

import pytest

from raspberry_controller.services.camera import MarkerDetectionResult
from raspberry_controller.services.laravel_api_client import ClaimedMission
from raspberry_controller.services.mission_executor import (
    MissionExecutionState,
    MissionExecutor,
)
from raspberry_controller.services.navigation.coordinator import (
    NavigationCoordinator,
    NavigationCoordinatorSettings,
)
from raspberry_controller.services.navigation.route_planner import (
    DirectedConnection,
    PhysicalNavigationMap,
    PhysicalNode,
    PhysicalRoom,
    ReturnRoute,
    RouteDecision,
    RouteStep,
)


INTERSECTION_EVENT = "EVENT|INTERSECTION|PATTERN=11111"
INTERSECTION_COMPLETE = "EVENT|INTERSECTION_COMPLETE|DIRECTION=LEFT"
INTERSECTION_FAILED = "EVENT|INTERSECTION_FAILED|DIRECTION=LEFT"
U_TURN_COMPLETE = "EVENT|U_TURN_COMPLETE|PATTERN=11011"


def approved_navigation_map() -> PhysicalNavigationMap:
    nodes = (
        PhysicalNode(1, "NODE_0", "intersection", 0),
        PhysicalNode(2, "NODE_1", "intersection", 1),
        PhysicalNode(3, "NODE_2", "intersection", 2),
        PhysicalNode(4, "ROOM_1", "room", 11),
        PhysicalNode(5, "ROOM_2", "room", 12),
        PhysicalNode(6, "ROOM_3", "room", 13),
        PhysicalNode(7, "ROOM_4", "room", 14),
        PhysicalNode(8, "ROOM_5", "room", 15),
    )
    rooms = tuple(
        PhysicalRoom(
            room_number,
            str(room_number),
            f"Room {room_number}",
            f"ROOM_{room_number}",
            10 + room_number,
        )
        for room_number in range(1, 6)
    )
    connections = (
        DirectedConnection("NODE_0", "ROOM_1", RouteDecision.LEFT),
        DirectedConnection("NODE_0", "NODE_1", RouteDecision.STRAIGHT),
        DirectedConnection("NODE_1", "NODE_2", RouteDecision.LEFT),
        DirectedConnection("NODE_1", "ROOM_4", RouteDecision.RIGHT),
        DirectedConnection("NODE_1", "ROOM_5", RouteDecision.STRAIGHT),
        DirectedConnection("NODE_2", "ROOM_3", RouteDecision.LEFT),
        DirectedConnection("NODE_2", "ROOM_2", RouteDecision.RIGHT),
    )
    return_routes = (
        ReturnRoute(1, (RouteStep("ROOM_1", RouteDecision.U_TURN, "NODE_0"),)),
        ReturnRoute(2, (
            RouteStep("ROOM_2", RouteDecision.U_TURN, "NODE_2"),
            RouteStep("NODE_2", RouteDecision.LEFT, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.RIGHT, "NODE_0"),
        )),
        ReturnRoute(3, (
            RouteStep("ROOM_3", RouteDecision.U_TURN, "NODE_2"),
            RouteStep("NODE_2", RouteDecision.RIGHT, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.RIGHT, "NODE_0"),
        )),
        ReturnRoute(4, (
            RouteStep("ROOM_4", RouteDecision.U_TURN, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.LEFT, "NODE_0"),
        )),
        ReturnRoute(5, (
            RouteStep("ROOM_5", RouteDecision.U_TURN, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.STRAIGHT, "NODE_0"),
        )),
    )
    return PhysicalNavigationMap(rooms, nodes, connections, return_routes)


def mission_for_room(room_id: int) -> ClaimedMission:
    return ClaimedMission(
        id=100 + room_id,
        room_id=room_id,
        medicine_id=2,
        quantity=1,
        room_number=str(room_id),
        dispenser_box=1,
        schedule_claimed_at="2026-08-10T09:00:00+00:00",
    )


class FakeCamera:
    def __init__(self, *detections: MarkerDetectionResult) -> None:
        self.detections = list(detections)
        self.calls = 0
        self.expected_marker_ids: list[int | None] = []
        self.after_sequences: list[int | None] = []
        self.frame_sequence = 100

    def current_frame_sequence(self) -> int:
        return self.frame_sequence

    def detect(
        self,
        *,
        expected_marker_id: int | None = None,
        after_sequence: int | None = None,
    ) -> MarkerDetectionResult:
        self.calls += 1
        self.expected_marker_ids.append(expected_marker_id)
        self.after_sequences.append(after_sequence)
        if not self.detections:
            raise AssertionError("No camera detection was configured")
        if len(self.detections) == 1:
            return self.detections[0]
        return self.detections.pop(0)


class HardwareRecorder:
    def __init__(self) -> None:
        self.navigation: list[str] = []
        self.line: list[str] = []
        self.dispense: list[object] = []
        self.water: list[object] = []
        self.return_home: list[object] = []
        self.command_event = threading.Event()
        self.dispense_event = threading.Event()
        self.return_started_event = threading.Event()

    def command(self, direction: str) -> str:
        self.navigation.append(direction)
        self.command_event.set()
        return f"ACK|INTERSECTION_{direction}_STARTED"

    def stop_line_follow(self) -> str:
        self.line.append("stop")
        return "ACK|LINE_FOLLOW_STOPPED"

    def u_turn(self) -> str:
        self.navigation.append("U_TURN")
        self.return_started_event.set()
        return "ACK|U_TURN_STARTED"

    def dispense_medicine(self, box_number: int, quantity: int) -> dict[str, int]:
        self.dispense.append((box_number, quantity))
        self.dispense_event.set()
        return {
            "box_number": box_number,
            "requested_pills": quantity,
            "dispensed_pills": quantity,
        }


def confirmed_marker(marker_id: int) -> MarkerDetectionResult:
    return MarkerDetectionResult(
        camera_available=True,
        detected=True,
        confirmed=True,
        marker_id=marker_id,
        node_name=None,
        marker_type=None,
        area=3600,
        consecutive_frames=3,
    )


def going_executor(
    room_id: int,
    *,
    load_map: Callable[[], PhysicalNavigationMap] | None = approved_navigation_map,
    u_turn: Callable[[], str] | None = None,
    dispense_medicine: Callable[[int, int], dict[str, int]] | None = None,
) -> MissionExecutor:
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=lambda: "ACK|LINE_FOLLOW_STARTED",
        stop_line_follow=lambda: "ACK|LINE_FOLLOW_STOPPED",
        u_turn=u_turn,
        dispense_medicine=dispense_medicine,
        mark_mission_in_progress=lambda mission: None,
        load_navigation_map=load_map,
    )
    assert executor.accept(mission_for_room(room_id)) is True
    assert executor.start_ready_mission().success is True
    assert executor.state is MissionExecutionState.GOING_TO_ROOM
    return executor


def arrived_executor(
    room_id: int,
    hardware: HardwareRecorder,
) -> MissionExecutor:
    executor = going_executor(
        room_id,
        u_turn=hardware.u_turn,
        dispense_medicine=hardware.dispense_medicine,
    )
    executor.mark_arrived_at_room()
    return executor


def coordinator(
    executor: MissionExecutor,
    camera: FakeCamera,
    hardware: HardwareRecorder,
    *,
    enabled: bool = True,
    arrived_home_observation_seconds: float = 1.0,
) -> NavigationCoordinator:
    return NavigationCoordinator(
        settings=NavigationCoordinatorSettings(
            enabled=enabled,
            arrived_home_observation_seconds=arrived_home_observation_seconds,
        ),
        executor=executor,
        camera_service=camera,  # type: ignore[arg-type]
        next_serial_event=lambda timeout: None,
        intersection_left=lambda: hardware.command("LEFT"),
        intersection_right=lambda: hardware.command("RIGHT"),
        intersection_straight=lambda: hardware.command("STRAIGHT"),
        stop_line_follow=hardware.stop_line_follow,
    )


def test_navigation_auto_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NAVIGATION_AUTO_ENABLED", raising=False)

    assert NavigationCoordinatorSettings.from_environment().enabled is False


def test_disabled_navigation_observes_event_and_sends_no_commands() -> None:
    executor = MissionExecutor(load_navigation_map=approved_navigation_map)
    route_planner = Mock(side_effect=AssertionError("route planner called"))
    executor.plan_route = route_planner  # type: ignore[method-assign]
    camera = FakeCamera(confirmed_marker(0))
    hardware = HardwareRecorder()
    service = coordinator(executor, camera, hardware, enabled=False)

    service.process_serial_line(INTERSECTION_EVENT)

    status = service.status()
    assert status["last_intersection_event"] == INTERSECTION_EVENT
    assert status["state"] == "DISABLED"
    assert status["last_command"] is None
    assert status["last_error"] is None
    assert executor.state is MissionExecutionState.IDLE
    assert hardware.navigation == []
    assert hardware.line == []
    assert camera.calls == 0
    route_planner.assert_not_called()


def test_background_event_consumer_runs_the_real_coordinator_flow() -> None:
    events: queue.Queue[str] = queue.Queue()
    hardware = HardwareRecorder()

    def next_event(timeout: float) -> str | None:
        try:
            return events.get(timeout=timeout)
        except queue.Empty:
            return None

    service = NavigationCoordinator(
        settings=NavigationCoordinatorSettings(enabled=True),
        executor=going_executor(1),
        camera_service=FakeCamera(confirmed_marker(0)),  # type: ignore[arg-type]
        next_serial_event=next_event,
        intersection_left=lambda: hardware.command("LEFT"),
        intersection_right=lambda: hardware.command("RIGHT"),
        intersection_straight=lambda: hardware.command("STRAIGHT"),
        stop_line_follow=hardware.stop_line_follow,
    )

    service.start()
    try:
        events.put(INTERSECTION_EVENT)
        assert hardware.command_event.wait(timeout=1.0)
    finally:
        service.stop()

    assert hardware.navigation == ["LEFT"]


@pytest.mark.parametrize(
    ("room_id", "marker_id", "expected"),
    [
        (1, 0, "LEFT"),
        (2, 0, "STRAIGHT"),
        (2, 1, "LEFT"),
        (2, 2, "RIGHT"),
        (3, 0, "STRAIGHT"),
        (3, 1, "LEFT"),
        (3, 2, "LEFT"),
        (4, 0, "STRAIGHT"),
        (4, 1, "RIGHT"),
        (5, 0, "STRAIGHT"),
        (5, 1, "STRAIGHT"),
    ],
)
def test_all_approved_route_decisions_dispatch_exactly_one_command(
    room_id: int,
    marker_id: int,
    expected: str,
) -> None:
    hardware = HardwareRecorder()
    service = coordinator(
        going_executor(room_id),
        FakeCamera(confirmed_marker(marker_id)),
        hardware,
    )

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == [expected]
    assert service.status()["last_command"] == f"INTERSECTION_{expected}"


def test_duplicate_event_dispatches_once_and_completion_rearms() -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(0), confirmed_marker(1))
    service = coordinator(going_executor(2), camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["STRAIGHT"]
    assert service.status()["last_error"] == "DUPLICATE_INTERSECTION_EVENT"

    service.process_serial_line(INTERSECTION_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["STRAIGHT", "LEFT"]
    assert camera.expected_marker_ids == [None, 1]


@pytest.mark.parametrize("room_id", [2, 3])
def test_room_two_and_three_ignore_early_marker_two_and_use_fresh_marker_one(
    room_id: int,
) -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(2), confirmed_marker(1))
    # This represents continuous camera/preview activity before the physical
    # intersection event.  It must not supply the route decision.
    assert camera.detect().marker_id == 2
    service = coordinator(going_executor(room_id), camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["LEFT"]
    assert camera.expected_marker_ids == [None, None]
    assert camera.after_sequences == [None, 100]
    assert service.status()["last_marker_id"] == 1
    assert service.status()["last_node"] == "NODE_1"


@pytest.mark.parametrize(
    ("room_id", "marker_id", "expected_command"),
    [(1, 0, "LEFT"), (4, 0, "STRAIGHT"), (5, 0, "STRAIGHT")],
)
def test_room_one_four_and_five_keep_existing_detection_timing(
    room_id: int,
    marker_id: int,
    expected_command: str,
) -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(marker_id))
    service = coordinator(going_executor(room_id), camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == [expected_command]
    assert camera.after_sequences == [None]


def test_room_two_area_first_selection_is_applied_after_intersection_event() -> None:
    hardware = HardwareRecorder()
    dominant_marker_one = MarkerDetectionResult(
        camera_available=True,
        detected=True,
        confirmed=True,
        marker_id=1,
        area=50000,
        second_marker_id=2,
        second_area=10000,
        area_ratio=5.0,
    )
    camera = FakeCamera(dominant_marker_one)
    service = coordinator(going_executor(2), camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["LEFT"]
    assert camera.after_sequences == [100]
    assert service.status()["last_marker_id"] == 1
    assert service.status()["last_second_marker_id"] == 2


def test_room_three_without_fresh_confirmation_fails_without_movement() -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(
        MarkerDetectionResult(
            camera_available=True,
            detected=True,
            confirmed=False,
            marker_id=1,
            area=50000,
            consecutive_frames=2,
        )
    )
    service = coordinator(going_executor(3), camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert camera.after_sequences == [100]
    assert service.status()["last_error"] == "MARKER_NOT_CONFIRMED"


def test_ambiguous_marker_selection_sends_zero_hardware_commands() -> None:
    hardware = HardwareRecorder()
    ambiguous = MarkerDetectionResult(
        camera_available=True,
        detected=True,
        confirmed=False,
        marker_id=0,
        area=30000,
        second_marker_id=1,
        second_area=28000,
        area_ratio=30000 / 28000,
        ambiguous=True,
        selection_error="AMBIGUOUS_MARKERS",
    )
    camera = FakeCamera(ambiguous)
    service = coordinator(going_executor(2), camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert hardware.line == []
    assert service.status()["last_error"] == "AMBIGUOUS_MARKERS"
    assert service.status()["last_selection_ambiguous"] is True
    assert service.status()["last_second_marker_id"] == 1
    assert camera.after_sequences == [100]


def test_unexpected_route_marker_sends_zero_hardware_commands() -> None:
    hardware = HardwareRecorder()
    unexpected = MarkerDetectionResult(
        camera_available=True,
        detected=True,
        confirmed=False,
        marker_id=0,
        area=50000,
        expected_marker_id=1,
        selection_error="UNEXPECTED_MARKER",
    )
    service = coordinator(going_executor(2), FakeCamera(unexpected), hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert service.status()["last_error"] == "UNEXPECTED_MARKER"


def test_expected_room_marker_is_used_for_arrival_after_previous_decision() -> None:
    hardware = HardwareRecorder()
    executor = going_executor(
        1,
        u_turn=hardware.u_turn,
        dispense_medicine=hardware.dispense_medicine,
    )
    camera = FakeCamera(confirmed_marker(0), confirmed_marker(11))
    service = coordinator(executor, camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)
    assert service.status()["expected_marker_id"] == 11
    service.process_serial_line(INTERSECTION_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert camera.expected_marker_ids == [None, 11]
    assert hardware.dispense_event.wait(timeout=1.0)
    assert hardware.return_started_event.wait(timeout=1.0)
    assert hardware.navigation == ["LEFT", "U_TURN"]
    assert hardware.line == ["stop"]
    assert hardware.dispense == [(1, 1)]
    assert executor.state is MissionExecutionState.RETURNING_HOME
    assert service.status()["expected_marker_id"] == 0


def test_failed_maneuver_is_reported_and_does_not_rearm() -> None:
    hardware = HardwareRecorder()
    service = coordinator(
        going_executor(1),
        FakeCamera(confirmed_marker(0)),
        hardware,
    )

    service.process_serial_line(INTERSECTION_EVENT)
    service.process_serial_line(INTERSECTION_FAILED)
    assert service.status()["last_error"] == "INTERSECTION_MANEUVER_FAILED"
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["LEFT"]
    assert service.status()["armed"] is False
    assert service.status()["last_error"] == "DUPLICATE_INTERSECTION_EVENT"


@pytest.mark.parametrize(
    ("detection", "error_code"),
    [
        (
            MarkerDetectionResult(False, False, False),
            "CAMERA_UNAVAILABLE",
        ),
        (
            MarkerDetectionResult(True, False, False),
            "MARKER_NOT_CONFIRMED",
        ),
    ],
)
def test_camera_failure_sends_no_command(
    detection: MarkerDetectionResult,
    error_code: str,
) -> None:
    hardware = HardwareRecorder()
    service = coordinator(going_executor(1), FakeCamera(detection), hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert service.status()["last_error"] == error_code


@pytest.mark.parametrize(
    ("room_id", "marker_id", "error_code"),
    [
        (1, 99, "UNKNOWN_MARKER"),
        (1, 1, "NO_ROUTE"),
    ],
)
def test_unknown_marker_and_no_route_send_no_command(
    room_id: int,
    marker_id: int,
    error_code: str,
) -> None:
    hardware = HardwareRecorder()
    service = coordinator(
        going_executor(room_id),
        FakeCamera(confirmed_marker(marker_id)),
        hardware,
    )

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert service.status()["last_error"] == error_code


def test_missing_laravel_map_sends_no_command() -> None:
    hardware = HardwareRecorder()
    service = coordinator(
        going_executor(1, load_map=None),
        FakeCamera(confirmed_marker(0)),
        hardware,
    )

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert service.status()["last_error"] == "MISSION_ROUTE_UNAVAILABLE"


@pytest.mark.parametrize("load_mission", [False, True])
def test_missing_mission_and_wrong_executor_state_send_no_command(
    load_mission: bool,
) -> None:
    executor = MissionExecutor(load_navigation_map=approved_navigation_map)
    if load_mission:
        assert executor.accept(mission_for_room(1)) is True
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(0))
    service = coordinator(executor, camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert camera.calls == 0
    assert service.status()["last_error"] == "EXECUTOR_NOT_GOING_TO_ROOM"


def test_arrived_automatically_dispenses_and_retains_mission() -> None:
    hardware = HardwareRecorder()
    executor = going_executor(
        1,
        u_turn=hardware.u_turn,
        dispense_medicine=hardware.dispense_medicine,
    )
    mission_id = executor.mission_id
    service = coordinator(
        executor,
        FakeCamera(confirmed_marker(11)),
        hardware,
    )

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.dispense_event.wait(timeout=1.0)
    assert hardware.return_started_event.wait(timeout=1.0)
    assert hardware.navigation == ["U_TURN"]
    assert hardware.line == ["stop"]
    assert hardware.dispense == [(1, 1)]
    assert hardware.water == []
    assert hardware.return_home == []
    assert executor.state is MissionExecutionState.RETURNING_HOME
    assert executor.mission_id == mission_id
    assert service.status()["state"] == "RETURNING_HOME"


def test_room_arrival_exposes_dispensing_while_uno_is_busy() -> None:
    hardware = HardwareRecorder()
    release_dispense = threading.Event()

    def blocking_dispense(box_number: int, quantity: int) -> dict[str, int]:
        hardware.dispense.append((box_number, quantity))
        hardware.dispense_event.set()
        assert release_dispense.wait(timeout=1.0)
        return {
            "box_number": box_number,
            "requested_pills": quantity,
            "dispensed_pills": quantity,
        }

    executor = going_executor(
        1,
        u_turn=hardware.u_turn,
        dispense_medicine=blocking_dispense,
    )
    service = coordinator(executor, FakeCamera(confirmed_marker(11)), hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.dispense_event.wait(timeout=1.0)
    assert executor.status()["state"] == "DISPENSING"
    assert service.status()["state"] == "DISPENSING"
    assert hardware.navigation == []

    release_dispense.set()
    assert hardware.return_started_event.wait(timeout=1.0)
    assert executor.state is MissionExecutionState.RETURNING_HOME


def test_duplicate_room_arrival_never_dispenses_or_turns_twice() -> None:
    hardware = HardwareRecorder()
    executor = going_executor(
        1,
        u_turn=hardware.u_turn,
        dispense_medicine=hardware.dispense_medicine,
    )
    service = coordinator(executor, FakeCamera(confirmed_marker(11)), hardware)

    service.process_serial_line(INTERSECTION_EVENT)
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.dispense_event.wait(timeout=1.0)
    assert hardware.return_started_event.wait(timeout=1.0)
    assert hardware.dispense == [(1, 1)]
    assert hardware.navigation == ["U_TURN"]


def test_dispense_quantity_two_must_complete_two_before_return() -> None:
    hardware = HardwareRecorder()
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=lambda: "ACK|LINE_FOLLOW_STARTED",
        stop_line_follow=lambda: "ACK|LINE_FOLLOW_STOPPED",
        u_turn=hardware.u_turn,
        dispense_medicine=hardware.dispense_medicine,
        mark_mission_in_progress=lambda mission: None,
        load_navigation_map=approved_navigation_map,
    )
    mission = mission_for_room(1)
    mission = ClaimedMission(
        mission.id,
        mission.room_id,
        mission.medicine_id,
        2,
        room_number=mission.room_number,
        dispenser_box=mission.dispenser_box,
        schedule_claimed_at=mission.schedule_claimed_at,
    )
    executor.accept(mission)
    executor.start_ready_mission()
    service = coordinator(executor, FakeCamera(confirmed_marker(11)), hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.dispense_event.wait(timeout=1.0)
    assert hardware.return_started_event.wait(timeout=1.0)
    assert hardware.dispense == [(1, 2)]
    assert hardware.navigation == ["U_TURN"]


@pytest.mark.parametrize("failure", ["mismatch", "exception"])
def test_dispense_failure_enters_failed_and_never_starts_return(
    failure: str,
) -> None:
    hardware = HardwareRecorder()

    def fail_dispense(box_number: int, quantity: int) -> dict[str, int]:
        hardware.dispense.append((box_number, quantity))
        hardware.dispense_event.set()
        if failure == "exception":
            raise RuntimeError("UNO unavailable")
        return {
            "box_number": box_number,
            "requested_pills": quantity,
            "dispensed_pills": quantity - 1,
        }

    executor = going_executor(
        1,
        u_turn=hardware.u_turn,
        dispense_medicine=fail_dispense,
    )
    service = coordinator(executor, FakeCamera(confirmed_marker(11)), hardware)

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.dispense_event.wait(timeout=1.0)
    service.stop()
    assert executor.state is MissionExecutionState.FAILED
    assert executor.status()["last_error"].startswith("DISPENSE_FAILED:")
    assert hardware.navigation == []
    assert hardware.water == []
    assert service.status()["last_error"] == "DISPENSE_FAILED"


def test_room_one_full_automatic_arrival_dispense_return_home_chain() -> None:
    hardware = HardwareRecorder()
    executor = going_executor(
        1,
        u_turn=hardware.u_turn,
        dispense_medicine=hardware.dispense_medicine,
    )
    mission_id = executor.mission_id
    camera = FakeCamera(confirmed_marker(11), confirmed_marker(0))
    service = coordinator(executor, camera, hardware)

    service.process_serial_line(INTERSECTION_EVENT)
    assert hardware.return_started_event.wait(timeout=1.0)
    assert executor.state is MissionExecutionState.RETURNING_HOME

    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert executor.state is MissionExecutionState.ARRIVED_HOME
    assert executor.mission_id == mission_id
    assert hardware.dispense == [(1, 1)]
    assert hardware.navigation == ["U_TURN"]
    assert hardware.line == ["stop", "stop"]
    assert hardware.water == []
    assert service.status()["state"] == "ARRIVED_HOME"


def test_return_home_requires_arrived_state_and_sends_no_command_otherwise() -> None:
    hardware = HardwareRecorder()
    executor = going_executor(1, u_turn=hardware.u_turn)
    service = coordinator(executor, FakeCamera(), hardware)

    result = service.begin_return_home()

    assert result["success"] is False
    assert result["result"] == "RETURN_NOT_ALLOWED"
    assert hardware.navigation == []


def test_return_u_turn_runs_once_and_stale_arrival_event_cannot_move() -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(0))
    executor = arrived_executor(1, hardware)
    service = coordinator(executor, camera, hardware)

    first = service.begin_return_home()
    second = service.begin_return_home()
    service.process_serial_line(INTERSECTION_EVENT)

    assert first["result"] == "RETURN_STARTED"
    assert second["result"] == "RETURN_NOT_ALLOWED"
    assert hardware.navigation == ["U_TURN"]
    assert camera.calls == 0
    assert service.status()["expected_marker_id"] == 0


def test_room_two_return_home_keeps_existing_detection_timing() -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(0))
    executor = arrived_executor(2, hardware)
    service = coordinator(executor, camera, hardware)

    assert service.begin_return_home()["result"] == "RETURN_STARTED"
    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["U_TURN"]
    assert camera.after_sequences == [None]
    assert executor.state is MissionExecutionState.ARRIVED_HOME


@pytest.mark.parametrize(
    ("room_id", "room_marker", "next_marker", "decision", "following_marker"),
    [
        (2, 12, 2, "LEFT", 1),
        (3, 13, 2, "RIGHT", 1),
        (4, 14, 1, "LEFT", 0),
        (5, 15, 1, "STRAIGHT", 0),
    ],
)
def test_returning_home_accepts_route_decisions_and_advances_expected_marker(
    room_id: int,
    room_marker: int,
    next_marker: int,
    decision: str,
    following_marker: int,
) -> None:
    hardware = HardwareRecorder()
    camera = FakeCamera(confirmed_marker(next_marker))
    executor = arrived_executor(room_id, hardware)
    service = coordinator(executor, camera, hardware)

    result = service.begin_return_home()
    assert result["expected_marker_id"] == next_marker
    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert executor.state is MissionExecutionState.RETURNING_HOME
    assert camera.expected_marker_ids == [next_marker]
    assert hardware.navigation == ["U_TURN", decision]
    assert service.status()["expected_marker_id"] == following_marker


def test_unexpected_marker_while_returning_fails_without_direction_command() -> None:
    hardware = HardwareRecorder()
    unexpected = MarkerDetectionResult(
        camera_available=True,
        detected=True,
        confirmed=False,
        marker_id=1,
        area=50000,
        expected_marker_id=2,
        selection_error="UNEXPECTED_MARKER",
    )
    executor = arrived_executor(2, hardware)
    service = coordinator(executor, FakeCamera(unexpected), hardware)

    service.begin_return_home()
    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["U_TURN"]
    assert service.status()["last_error"] == "UNEXPECTED_MARKER"


def test_marker_zero_stops_and_marks_arrived_home_without_completing_mission() -> None:
    hardware = HardwareRecorder()
    executor = arrived_executor(1, hardware)
    mission_id = executor.mission_id
    service = coordinator(executor, FakeCamera(confirmed_marker(0)), hardware)

    service.begin_return_home()
    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == ["U_TURN"]
    assert hardware.line == ["stop"]
    assert hardware.dispense == []
    assert hardware.water == []
    assert executor.state is MissionExecutionState.ARRIVED_HOME
    assert executor.mission_id == mission_id
    assert service.status()["state"] == "ARRIVED_HOME"
    assert service.status()["last_marker_id"] == 0
    assert service.status()["last_node"] == "NODE_0"
    assert service.status()["last_decision"] == "ARRIVED"
    assert service.status()["last_error"] is None


def test_arrived_home_is_observable_then_rearms_cleanly_without_stale_motion() -> None:
    hardware = HardwareRecorder()
    executor = arrived_executor(1, hardware)
    service = coordinator(
        executor,
        FakeCamera(confirmed_marker(0)),
        hardware,
        arrived_home_observation_seconds=0.01,
    )

    service.begin_return_home()
    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)

    # The confirmed NODE_0 arrival is available before the asynchronous reset.
    assert executor.state is MissionExecutionState.ARRIVED_HOME
    assert service.status()["state"] == "ARRIVED_HOME"
    assert service.status()["last_node"] == "NODE_0"

    finalization_thread = service._home_finalization_thread
    assert finalization_thread is not None
    finalization_thread.join(timeout=1.0)

    assert executor.status()["state"] == "IDLE"
    assert executor.mission_id is None
    assert service.status()["armed"] is True
    assert service.status()["expected_marker_id"] is None
    assert service.status()["last_marker_id"] == 0
    assert service.status()["last_node"] == "NODE_0"
    assert service.status()["last_decision"] == "ARRIVED"

    service.process_serial_line(INTERSECTION_EVENT)
    assert hardware.navigation == ["U_TURN"]
    assert service.status()["armed"] is True
    assert service.status()["last_error"] is None


def test_second_mission_starts_cleanly_after_arrived_home_cleanup() -> None:
    hardware = HardwareRecorder()
    executor = arrived_executor(1, hardware)
    service = coordinator(
        executor,
        FakeCamera(confirmed_marker(0), confirmed_marker(0)),
        hardware,
        arrived_home_observation_seconds=0.01,
    )

    service.begin_return_home()
    service.process_serial_line(U_TURN_COMPLETE)
    service.process_serial_line(INTERSECTION_EVENT)
    finalization_thread = service._home_finalization_thread
    assert finalization_thread is not None
    finalization_thread.join(timeout=1.0)

    second_mission = mission_for_room(1)
    second_mission = ClaimedMission(
        id=second_mission.id + 1000,
        room_id=second_mission.room_id,
        medicine_id=second_mission.medicine_id,
        quantity=second_mission.quantity,
        room_number=second_mission.room_number,
        dispenser_box=second_mission.dispenser_box,
        schedule_claimed_at=second_mission.schedule_claimed_at,
    )
    assert executor.accept(second_mission) is True
    assert executor.start_ready_mission().success is True

    service.process_serial_line(INTERSECTION_EVENT)

    assert executor.state is MissionExecutionState.GOING_TO_ROOM
    assert hardware.navigation == ["U_TURN", "LEFT"]
    assert hardware.line == ["stop"]
    assert hardware.dispense == []
    assert hardware.water == []


def test_disabled_preview_never_moves_or_changes_executor_state() -> None:
    executor = MissionExecutor(load_navigation_map=approved_navigation_map)
    route_planner = Mock(side_effect=AssertionError("route planner called"))
    executor.plan_route = route_planner  # type: ignore[method-assign]
    camera = FakeCamera(confirmed_marker(11))
    hardware = HardwareRecorder()
    service = coordinator(
        executor,
        camera,
        hardware,
        enabled=False,
    )

    status = service.preview_test_intersection()

    assert hardware.navigation == []
    assert hardware.line == []
    assert camera.calls == 0
    route_planner.assert_not_called()
    assert executor.state is MissionExecutionState.IDLE
    assert status["last_intersection_event"] == (
        "EVENT|INTERSECTION|SOURCE=TEST"
    )
    assert status["state"] == "DISABLED"
    assert status["last_command"] is None
    assert status["last_error"] is None
