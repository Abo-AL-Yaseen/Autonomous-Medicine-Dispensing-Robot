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
    RouteDecision,
)


INTERSECTION_EVENT = "EVENT|INTERSECTION|PATTERN=11111"
INTERSECTION_COMPLETE = "EVENT|INTERSECTION_COMPLETE|DIRECTION=LEFT"
INTERSECTION_FAILED = "EVENT|INTERSECTION_FAILED|DIRECTION=LEFT"


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
    return PhysicalNavigationMap(rooms, nodes, connections)


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

    def detect(self) -> MarkerDetectionResult:
        self.calls += 1
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

    def command(self, direction: str) -> str:
        self.navigation.append(direction)
        self.command_event.set()
        return f"ACK|INTERSECTION_{direction}_STARTED"

    def stop_line_follow(self) -> str:
        self.line.append("stop")
        return "ACK|LINE_FOLLOW_STOPPED"


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
) -> MissionExecutor:
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=lambda: "ACK|LINE_FOLLOW_STARTED",
        stop_line_follow=lambda: "ACK|LINE_FOLLOW_STOPPED",
        mark_mission_in_progress=lambda mission: None,
        load_navigation_map=load_map,
    )
    assert executor.accept(mission_for_room(room_id)) is True
    assert executor.start_ready_mission().success is True
    assert executor.state is MissionExecutionState.GOING_TO_ROOM
    return executor


def coordinator(
    executor: MissionExecutor,
    camera: FakeCamera,
    hardware: HardwareRecorder,
    *,
    enabled: bool = True,
) -> NavigationCoordinator:
    return NavigationCoordinator(
        settings=NavigationCoordinatorSettings(enabled=enabled),
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


def test_arrived_stops_line_follow_but_does_not_deliver_or_release_mission() -> None:
    executor = going_executor(1)
    mission_id = executor.mission_id
    hardware = HardwareRecorder()
    service = coordinator(
        executor,
        FakeCamera(confirmed_marker(11)),
        hardware,
    )

    service.process_serial_line(INTERSECTION_EVENT)

    assert hardware.navigation == []
    assert hardware.line == ["stop"]
    assert hardware.dispense == []
    assert hardware.water == []
    assert hardware.return_home == []
    assert executor.state is MissionExecutionState.ARRIVED_AT_ROOM
    assert executor.mission_id == mission_id
    assert service.status()["state"] == "ARRIVED_AT_ROOM"


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
