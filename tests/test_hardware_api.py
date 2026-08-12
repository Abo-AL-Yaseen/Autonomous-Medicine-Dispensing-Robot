"""API tests that replace all real serial hardware with an in-memory fake."""

from __future__ import annotations

import queue
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from raspberry_controller.api import (
    HardwareSettings,
    WaterCalibrationError,
    calculate_water_duration_ms,
    create_app,
)
from raspberry_controller.hardware_controller import SerialConnectionError
from raspberry_controller.services.camera import (
    ArucoCameraService,
    CameraSettings,
    MarkerDetectionResult,
)
from raspberry_controller.services.laravel_api_client import ClaimedMission
from raspberry_controller.services.mission_executor import (
    MissionExecutionState,
    MissionExecutor,
)
from raspberry_controller.services.navigation import (
    DirectedConnection,
    PhysicalNavigationMap,
    PhysicalNode,
    PhysicalRoom,
    ReturnRoute,
    RouteDecision,
    RouteStep,
)
from raspberry_controller.services.mission_scheduler import SchedulerSettings


class FakeHardwareController:
    """Record API-to-hardware calls without opening serial devices."""

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.dispense_calls: list[tuple[int, int]] = []
        self.movement_calls: list[str] = []
        self.line_calls: list[str] = []
        self.navigation_calls: list[str] = []
        self.rtc_calls = 0
        self.water_calls: list[int] = []
        self.hardware_error: Exception | None = None
        self.line_start_response = "ACK|LINE_FOLLOW_STARTED"
        self.line_stop_response = "ACK|LINE_FOLLOW_STOPPED"
        self.line_start_error: Exception | None = None
        self.camera_calls: list[str] = []
        self.return_home_calls: list[str] = []
        self.esp32_events: queue.Queue[str] = queue.Queue()

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True
        self.connected = False

    def ping_all(self) -> dict[str, str]:
        self._raise_hardware_error()
        return {"ESP32": "ACK|PING", "ARDUINO_UNO": "ACK|PING"}

    def get_all_statuses(self) -> dict[str, str]:
        self._raise_hardware_error()
        return {"ESP32": "STATUS|IDLE", "ARDUINO_UNO": "STATUS|IDLE"}

    def dispense(self, box_number: int, pill_count: int) -> dict[str, int]:
        self._raise_hardware_error()
        self.dispense_calls.append((box_number, pill_count))
        return {
            "box_number": box_number,
            "requested_pills": pill_count,
            "dispensed_pills": pill_count,
        }

    def get_rtc_datetime(self) -> datetime:
        self._raise_hardware_error()
        self.rtc_calls += 1
        return datetime(2026, 8, 9, 20, 30, 0)

    def dispense_water(self, duration_ms: int) -> dict[str, int]:
        self._raise_hardware_error()
        self.water_calls.append(duration_ms)
        return {"duration_ms": duration_ms}

    def forward(self) -> str:
        return self._record_movement("forward", "ACK|FORWARD")

    def backward(self) -> str:
        return self._record_movement("backward", "ACK|BACKWARD")

    def turn_left(self) -> str:
        return self._record_movement("left", "ACK|LEFT")

    def turn_right(self) -> str:
        return self._record_movement("right", "ACK|RIGHT")

    def stop(self) -> str:
        return self._record_movement("stop", "ACK|STOP")

    def manual_forward(self) -> str:
        return self._record_movement("manual-forward", "ACK|MANUAL_FORWARD")

    def manual_backward(self) -> str:
        return self._record_movement("manual-backward", "ACK|MANUAL_BACKWARD")

    def manual_left(self) -> str:
        return self._record_movement("manual-left", "ACK|MANUAL_LEFT")

    def manual_right(self) -> str:
        return self._record_movement("manual-right", "ACK|MANUAL_RIGHT")

    def manual_forward_left(self) -> str:
        return self._record_movement(
            "manual-forward-left",
            "ACK|MANUAL_FORWARD_LEFT",
        )

    def manual_forward_right(self) -> str:
        return self._record_movement(
            "manual-forward-right",
            "ACK|MANUAL_FORWARD_RIGHT",
        )

    def manual_backward_left(self) -> str:
        return self._record_movement(
            "manual-backward-left",
            "ACK|MANUAL_BACKWARD_LEFT",
        )

    def manual_backward_right(self) -> str:
        return self._record_movement(
            "manual-backward-right",
            "ACK|MANUAL_BACKWARD_RIGHT",
        )

    def manual_stop(self) -> str:
        return self._record_movement("manual-stop", "ACK|MANUAL_STOP")

    def _record_movement(self, movement: str, response: str) -> str:
        self._raise_hardware_error()
        self.movement_calls.append(movement)
        return response

    def get_line_reading(self) -> str:
        return self._record_line_call(
            "get_line_reading",
            "LINE|O1=1|O2=1|O3=0|O4=1|O5=1|PATTERN=11011",
        )

    def get_line_status(self) -> str:
        return self._record_line_call(
            "get_line_status",
            "LINE_STATUS|MODE=FOLLOWING|STATE=SEARCHING_LEFT|PATTERN=11111",
        )

    def start_line_follow(self) -> str:
        self._raise_hardware_error()
        self.line_calls.append("start_line_follow")
        if self.line_start_error:
            raise self.line_start_error
        return self.line_start_response

    def stop_line_follow(self) -> str:
        return self._record_line_call(
            "stop_line_follow",
            self.line_stop_response,
        )

    def intersection_left(self) -> str:
        return self._record_navigation_call(
            "left",
            "ACK|INTERSECTION_LEFT_STARTED",
        )

    def intersection_right(self) -> str:
        return self._record_navigation_call(
            "right",
            "ACK|INTERSECTION_RIGHT_STARTED",
        )

    def intersection_straight(self) -> str:
        return self._record_navigation_call(
            "straight",
            "ACK|INTERSECTION_STRAIGHT_STARTED",
        )

    def get_esp32_event(self, timeout: float = 0.0) -> str | None:
        try:
            return self.esp32_events.get(timeout=timeout)
        except queue.Empty:
            return None

    def u_turn(self) -> str:
        return self._record_navigation_call(
            "u-turn",
            "ACK|U_TURN_STARTED",
        )

    def _record_line_call(self, method: str, response: str) -> str:
        self._raise_hardware_error()
        self.line_calls.append(method)
        return response

    def _record_navigation_call(self, direction: str, response: str) -> str:
        self._raise_hardware_error()
        self.navigation_calls.append(direction)
        return response

    def _raise_hardware_error(self) -> None:
        if self.hardware_error is not None:
            raise self.hardware_error


class FakeLaravelClient:
    def __init__(self) -> None:
        self.claimed_mission: ClaimedMission | None = None
        self.calls: list[tuple[datetime, str]] = []
        self.start_calls: list[ClaimedMission] = []
        self.start_error: Exception | None = None
        self.map_calls = 0
        self.navigation_map = _navigation_map_fixture()
        self.closed = False

    def claim_due_mission(
        self,
        robot_datetime: datetime,
        timezone_name: str,
    ) -> ClaimedMission | None:
        self.calls.append((robot_datetime, timezone_name))
        return self.claimed_mission

    def start_claimed_mission(self, mission: ClaimedMission) -> None:
        self.start_calls.append(mission)
        if self.start_error:
            raise self.start_error

    def get_navigation_map(self) -> PhysicalNavigationMap:
        self.map_calls += 1
        return self.navigation_map

    def close(self) -> None:
        self.closed = True


def _navigation_map_fixture() -> PhysicalNavigationMap:
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
    return_routes = tuple(
        ReturnRoute(
            room_id,
            (RouteStep(f"ROOM_{room_id}", RouteDecision.U_TURN, "NODE_0"),),
        )
        for room_id in range(1, 6)
    )
    return PhysicalNavigationMap(rooms, nodes, connections, return_routes)


class FakeCameraService:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.started = False
        self.closed = False
        self.detect_calls = 0
        self.preview_calls = 0
        self.stream_calls = 0
        self.detection = MarkerDetectionResult(
            camera_available=available,
            detected=True,
            confirmed=True,
            marker_id=1,
            node_name="NODE_1",
            marker_type="intersection",
            area=3600,
            consecutive_frames=3,
        )

    def start(self) -> bool:
        self.started = True
        return self.available

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "device": "/dev/video0",
            "camera_open": self.available,
            "camera_available": self.available,
            "dictionary": "DICT_4X4_50",
            "width": 640,
            "height": 480,
            "confirm_frames": 3,
            "min_marker_area": 2500.0,
            "min_area_ratio": 1.4,
            "error": None if self.available else "CAMERA_UNAVAILABLE",
        }

    def detect(
        self,
        *,
        expected_marker_id: int | None = None,
    ) -> MarkerDetectionResult:
        self.detect_calls += 1
        return self.detection

    def get_preview_jpeg(
        self,
        *,
        after_sequence: int | None = None,
        timeout: float = 1.0,
    ) -> tuple[int, bytes] | None:
        self.preview_calls += 1
        if not self.available:
            return None
        return 1, b"fake-jpeg"

    def mjpeg_stream(
        self,
        first_frame: tuple[int, bytes],
        *,
        fps: float = 12.0,
    ) -> Iterator[bytes]:
        self.stream_calls += 1
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + first_frame[1]


@pytest.fixture
def fake_hardware() -> FakeHardwareController:
    return FakeHardwareController()


@pytest.fixture
def fake_laravel() -> FakeLaravelClient:
    return FakeLaravelClient()


@pytest.fixture
def fake_camera() -> FakeCameraService:
    return FakeCameraService()


def executable_mission() -> ClaimedMission:
    return ClaimedMission(
        8,
        1,
        2,
        4,
        room_number="204",
        dispenser_box=1,
        schedule_claimed_at="2026-08-09T17:30:00+00:00",
    )


def test_robot_timezone_defaults_to_asia_hebron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBOT_TIMEZONE", raising=False)

    assert HardwareSettings.from_environment().robot_timezone == "Asia/Hebron"


@pytest.fixture
def client(
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
    fake_camera: FakeCameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("WATER_FLOW_ML_PER_SECOND", "50")
    monkeypatch.setenv("ROBOT_TIMEZONE", "Asia/Hebron")
    monkeypatch.setenv("MISSION_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MISSION_AUTO_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("NAVIGATION_AUTO_ENABLED", "false")
    monkeypatch.setenv("CAMERA_ENABLED", "true")

    def fake_factory(settings: HardwareSettings) -> FakeHardwareController:
        assert settings.esp32_port.startswith("/dev/serial/by-id/")
        assert settings.arduino_port.startswith("/dev/serial/by-id/")
        assert settings.water_flow_ml_per_second == 50
        assert settings.robot_timezone == "Asia/Hebron"
        return fake_hardware

    def fake_laravel_factory(settings: SchedulerSettings) -> FakeLaravelClient:
        assert settings.enabled is False
        assert settings.auto_execution_enabled is False
        return fake_laravel

    def fake_camera_factory(settings: CameraSettings) -> ArucoCameraService:
        assert settings.enabled is True
        assert settings.device == "/dev/video0"
        assert settings.confirm_frames == 3
        assert settings.min_marker_area == 2500.0
        assert settings.min_area_ratio == 1.4
        return fake_camera  # type: ignore[return-value]

    application = create_app(
        controller_factory=fake_factory,
        laravel_client_factory=fake_laravel_factory,
        camera_factory=fake_camera_factory,
    )
    with TestClient(application) as test_client:
        yield test_client

    assert fake_hardware.closed is True
    assert fake_laravel.closed is True
    assert fake_camera.closed is True


def test_root_lists_api_information(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Autonomous Medicine Dispensing Robot Hardware API"
    assert body["version"] == "1.0.0"
    assert "/camera/status" in body["endpoints"]
    assert "/camera/detect" in body["endpoints"]
    assert "/camera/stream" in body["endpoints"]
    assert "/dispense" in body["endpoints"]
    assert "/rtc" in body["endpoints"]
    assert "/scheduler/status" in body["endpoints"]
    assert "/scheduler/tick" in body["endpoints"]
    assert "/executor/status" in body["endpoints"]
    assert "/executor/start" in body["endpoints"]
    assert "/executor/return-home" in body["endpoints"]
    assert "/water/dispense" in body["endpoints"]
    assert "/movement/stop" in body["endpoints"]
    assert "/movement/manual/forward" in body["endpoints"]
    assert "/movement/manual/forward-right" in body["endpoints"]
    assert "/movement/manual/backward-left" in body["endpoints"]
    assert "/movement/manual/stop" in body["endpoints"]
    assert "/line/start" in body["endpoints"]
    assert "/line/stop" in body["endpoints"]
    assert "/navigation/intersection/left" in body["endpoints"]
    assert "/navigation/intersection/right" in body["endpoints"]
    assert "/navigation/intersection/straight" in body["endpoints"]
    assert "/navigation/u-turn" in body["endpoints"]
    assert "/navigation/route/current" in body["endpoints"]
    assert "/navigation/decision/preview" in body["endpoints"]
    assert "/navigation/status" in body["endpoints"]
    assert "/navigation/test/intersection-event" in body["endpoints"]


def test_health_reports_connected_hardware(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "running",
        "hardware_connected": True,
        "camera_available": True,
    }


def test_camera_status_reports_independent_camera_configuration(
    client: TestClient,
) -> None:
    response = client.get("/camera/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "device": "/dev/video0",
        "camera_open": True,
        "camera_available": True,
        "dictionary": "DICT_4X4_50",
        "width": 640,
        "height": 480,
        "confirm_frames": 3,
        "min_marker_area": 2500.0,
        "min_area_ratio": 1.4,
        "error": None,
    }


def test_camera_detect_is_read_only_and_returns_structured_detection(
    client: TestClient,
    fake_camera: FakeCameraService,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/camera/detect")

    assert response.status_code == 200
    assert response.json() == fake_camera.detection.as_dict()
    assert fake_camera.detect_calls == 1
    assert fake_hardware.movement_calls == []
    assert fake_hardware.line_calls == []
    assert fake_hardware.navigation_calls == []
    assert fake_hardware.dispense_calls == []
    assert fake_hardware.water_calls == []


def test_camera_stream_uses_existing_service_and_detect_still_works(
    client: TestClient,
    fake_camera: FakeCameraService,
    fake_hardware: FakeHardwareController,
) -> None:
    stream_response = client.get("/camera/stream")
    detect_response = client.post("/camera/detect")

    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith(
        "multipart/x-mixed-replace; boundary=frame"
    )
    assert b"fake-jpeg" in stream_response.content
    assert detect_response.status_code == 200
    assert fake_camera.preview_calls == 1
    assert fake_camera.stream_calls == 1
    assert fake_camera.detect_calls == 1
    assert fake_hardware.movement_calls == []
    assert fake_hardware.line_calls == []
    assert fake_hardware.navigation_calls == []


def test_navigation_decision_preview_uses_loaded_mission_without_hardware(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    executor: MissionExecutor = client.app.state.mission_executor
    mission = ClaimedMission(
        84,
        4,
        2,
        1,
        room_number="4",
        dispenser_box=1,
        schedule_claimed_at="2026-08-09T17:30:00+00:00",
    )
    assert executor.accept(mission) is True

    response = client.post(
        "/navigation/decision/preview",
        json={"marker_id": 0},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "mission_id": 84,
        "room_id": 4,
        "current_node": "NODE_0",
        "current_marker_id": 0,
        "destination_node": "ROOM_4",
        "destination_marker_id": 14,
        "decision": "STRAIGHT",
        "next_node": "NODE_1",
    }
    assert fake_laravel.map_calls == 1
    assert executor.state is MissionExecutionState.READY_FOR_EXECUTION
    assert fake_hardware.movement_calls == []
    assert fake_hardware.line_calls == []
    assert fake_hardware.navigation_calls == []
    assert fake_hardware.dispense_calls == []
    assert fake_hardware.water_calls == []


def test_navigation_status_reports_auto_disabled_by_default(
    client: TestClient,
) -> None:
    response = client.get("/navigation/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "state": "DISABLED",
        "mission_id": None,
        "armed": True,
        "last_intersection_event": None,
        "last_marker_id": None,
        "last_node": None,
        "last_decision": None,
        "last_command": None,
        "last_error": None,
        "expected_marker_id": None,
        "last_marker_area": None,
        "last_second_marker_id": None,
        "last_second_marker_area": None,
        "last_area_ratio": None,
        "last_selection_ambiguous": False,
    }


def test_disabled_intersection_test_endpoint_never_sends_hardware_command(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_camera: FakeCameraService,
    fake_laravel: FakeLaravelClient,
) -> None:
    executor: MissionExecutor = client.app.state.mission_executor

    response = client.post("/navigation/test/intersection-event")

    assert response.status_code == 200
    assert response.json()["last_intersection_event"] == (
        "EVENT|INTERSECTION|SOURCE=TEST"
    )
    assert response.json()["state"] == "DISABLED"
    assert response.json()["last_command"] is None
    assert response.json()["last_error"] is None
    assert executor.state is MissionExecutionState.IDLE
    assert fake_camera.detect_calls == 0
    assert fake_laravel.map_calls == 0
    assert fake_hardware.navigation_calls == []
    assert fake_hardware.line_calls == []
    assert fake_hardware.dispense_calls == []
    assert fake_hardware.water_calls == []


def test_current_navigation_route_returns_all_remaining_directed_steps(
    client: TestClient,
) -> None:
    executor: MissionExecutor = client.app.state.mission_executor
    executor.accept(
        ClaimedMission(
            82,
            2,
            2,
            1,
            room_number="2",
            dispenser_box=1,
            schedule_claimed_at="2026-08-09T17:30:00+00:00",
        )
    )

    response = client.get("/navigation/route/current", params={"marker_id": 0})

    assert response.status_code == 200
    assert response.json()["route"] == [
        {"from_node": "NODE_0", "direction": "STRAIGHT", "to_node": "NODE_1"},
        {"from_node": "NODE_1", "direction": "LEFT", "to_node": "NODE_2"},
        {"from_node": "NODE_2", "direction": "RIGHT", "to_node": "ROOM_2"},
    ]


def test_navigation_preview_reports_arrived_only_at_loaded_destination(
    client: TestClient,
) -> None:
    executor: MissionExecutor = client.app.state.mission_executor
    executor.accept(
        ClaimedMission(
            84,
            4,
            2,
            1,
            room_number="4",
            dispenser_box=1,
            schedule_claimed_at="2026-08-09T17:30:00+00:00",
        )
    )

    arrived = client.post(
        "/navigation/decision/preview",
        json={"marker_id": 14},
    )
    wrong_room_marker = client.post(
        "/navigation/decision/preview",
        json={"marker_id": 11},
    )

    assert arrived.status_code == 200
    assert arrived.json()["decision"] == "ARRIVED"
    assert arrived.json()["next_node"] is None
    assert wrong_room_marker.status_code == 200
    assert wrong_room_marker.json()["success"] is False
    assert wrong_room_marker.json()["decision"] == "NO_ROUTE"


def test_navigation_preview_rejects_unknown_marker_safely(
    client: TestClient,
) -> None:
    executor: MissionExecutor = client.app.state.mission_executor
    executor.accept(
        ClaimedMission(
            81,
            1,
            2,
            1,
            room_number="1",
            dispenser_box=1,
            schedule_claimed_at="2026-08-09T17:30:00+00:00",
        )
    )

    response = client.post(
        "/navigation/decision/preview",
        json={"marker_id": 99},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "UNKNOWN_MARKER"}}


def test_navigation_preview_requires_a_loaded_mission(client: TestClient) -> None:
    response = client.post(
        "/navigation/decision/preview",
        json={"marker_id": 0},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NO_LOADED_MISSION"}}


def test_health_still_works_when_camera_is_unavailable_at_startup(
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable_camera = FakeCameraService(available=False)
    monkeypatch.setenv("MISSION_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("MISSION_AUTO_EXECUTION_ENABLED", "false")

    application = create_app(
        controller_factory=lambda settings: fake_hardware,
        laravel_client_factory=lambda settings: fake_laravel,
        camera_factory=lambda settings: unavailable_camera,  # type: ignore[arg-type]
    )

    with TestClient(application) as test_client:
        response = test_client.get("/health")
        stream_response = test_client.get("/camera/stream")

        assert response.status_code == 200
        assert response.json() == {
            "status": "running",
            "hardware_connected": True,
            "camera_available": False,
        }
        assert fake_hardware.connected is True
        assert stream_response.status_code == 503
        assert stream_response.json() == {
            "detail": {"code": "CAMERA_UNAVAILABLE"}
        }


def test_ping_returns_both_board_responses(client: TestClient) -> None:
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "responses": {"ESP32": "ACK|PING", "ARDUINO_UNO": "ACK|PING"},
    }


def test_status_returns_both_board_statuses(client: TestClient) -> None:
    response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "statuses": {
            "ESP32": "STATUS|IDLE",
            "ARDUINO_UNO": "STATUS|IDLE",
        },
    }


def test_rtc_returns_ds1302_datetime(client: TestClient) -> None:
    response = client.get("/rtc")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "datetime": "2026-08-09T20:30:00",
        "source": "DS1302",
        "timezone": "Asia/Hebron",
    }


def test_rtc_hardware_unavailable_is_safe(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    client.app.state.hardware_connected = False

    response = client.get("/rtc")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "HARDWARE_UNAVAILABLE"}}
    assert fake_hardware.rtc_calls == 0


def test_scheduler_status_is_idle_and_disabled_by_default(
    client: TestClient,
) -> None:
    response = client.get("/scheduler/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "running": False,
        "state": "IDLE",
        "mission_id": None,
        "room_id": None,
        "room_number": None,
        "target_room": None,
        "medicine_id": None,
        "dispenser_box": None,
        "quantity": None,
        "last_error": None,
        "auto_execution_enabled": False,
        "pending_acceptance_mission_id": None,
        "last_tick_at": None,
        "last_result": None,
    }


def test_manual_scheduler_tick_is_safe_when_no_mission_is_due(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    response = client.post("/scheduler/tick")

    assert response.status_code == 200
    assert response.json()["result"] == "NO_DUE_MISSION"
    assert response.json()["executor"]["state"] == "IDLE"
    assert fake_hardware.rtc_calls == 1
    assert fake_laravel.calls == [
        (datetime(2026, 8, 9, 20, 30, 0), "Asia/Hebron")
    ]
    assert fake_hardware.movement_calls == []
    assert fake_hardware.dispense_calls == []
    assert fake_hardware.water_calls == []


def test_manual_scheduler_tick_only_prepares_claimed_mission(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    fake_laravel.claimed_mission = ClaimedMission(8, 1, 2, 4)

    response = client.post("/scheduler/tick")

    assert response.status_code == 200
    assert response.json()["result"] == "READY_FOR_EXECUTION"
    assert response.json()["executor"] == {
        "state": "READY_FOR_EXECUTION",
        "mission_id": 8,
        "room_id": 1,
        "room_number": None,
        "target_room": 1,
        "medicine_id": 2,
        "dispenser_box": None,
        "quantity": 4,
        "last_error": None,
        "auto_execution_enabled": False,
    }
    assert fake_hardware.movement_calls == []
    assert fake_hardware.line_calls == []
    assert fake_hardware.navigation_calls == []
    assert fake_hardware.dispense_calls == []
    assert fake_hardware.water_calls == []


def test_manual_scheduler_tick_does_not_claim_without_hardware(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    client.app.state.hardware_connected = False

    response = client.post("/scheduler/tick")

    assert response.status_code == 200
    assert response.json()["result"] == "HARDWARE_UNAVAILABLE"
    assert fake_hardware.rtc_calls == 0
    assert fake_laravel.calls == []


def test_executor_status_and_start_require_a_ready_mission(
    client: TestClient,
) -> None:
    status_response = client.get("/executor/status")
    start_response = client.post("/executor/start")

    assert status_response.status_code == 200
    assert status_response.json()["state"] == "IDLE"
    assert status_response.json()["auto_execution_enabled"] is False
    assert start_response.status_code == 409
    assert start_response.json()["result"] == "NO_READY_MISSION"


def test_executor_start_uses_high_level_line_follow_then_laravel(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    mission = executable_mission()
    assert client.app.state.mission_executor.accept(mission) is True

    first = client.post("/executor/start")
    second = client.post("/executor/start")

    assert first.status_code == 200
    assert first.json()["result"] == "STARTED"
    assert first.json()["executor"]["state"] == "GOING_TO_ROOM"
    assert second.status_code == 409
    assert second.json()["result"] == "EXECUTOR_BUSY"
    assert fake_hardware.line_calls == ["start_line_follow"]
    assert fake_laravel.start_calls == [mission]
    assert fake_hardware.movement_calls == []
    assert fake_hardware.navigation_calls == []
    assert fake_hardware.camera_calls == []
    assert fake_hardware.dispense_calls == []
    assert fake_hardware.water_calls == []
    assert fake_hardware.return_home_calls == []


def test_executor_return_home_rejects_non_arrived_state_without_movement(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/executor/return-home")

    assert response.status_code == 409
    assert response.json()["result"] == "RETURN_NOT_ALLOWED"
    assert fake_hardware.navigation_calls == []
    assert fake_hardware.line_calls == []


def test_executor_start_does_nothing_when_hardware_is_unavailable(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    client.app.state.mission_executor.accept(executable_mission())
    client.app.state.hardware_connected = False

    response = client.post("/executor/start")

    assert response.status_code == 503
    assert response.json()["result"] == "HARDWARE_UNAVAILABLE"
    assert response.json()["executor"]["state"] == "READY_FOR_EXECUTION"
    assert fake_hardware.line_calls == []
    assert fake_laravel.start_calls == []


def test_executor_malformed_start_ack_never_updates_laravel(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    client.app.state.mission_executor.accept(executable_mission())
    fake_hardware.line_start_response = "ACK|WRONG"

    response = client.post("/executor/start")

    assert response.status_code == 502
    assert response.json()["result"] == "LINE_FOLLOW_START_FAILED"
    assert response.json()["executor"]["state"] == "FAILED"
    assert fake_hardware.line_calls == [
        "start_line_follow",
        "stop_line_follow",
    ]
    assert fake_laravel.start_calls == []


def test_executor_laravel_failure_immediately_stops_line_follow(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    fake_laravel: FakeLaravelClient,
) -> None:
    client.app.state.mission_executor.accept(executable_mission())
    fake_laravel.start_error = RuntimeError("Laravel unavailable")

    response = client.post("/executor/start")

    assert response.status_code == 502
    assert response.json()["result"] == "MISSION_STATUS_UPDATE_FAILED"
    assert response.json()["executor"]["state"] == "FAILED"
    assert fake_hardware.line_calls == [
        "start_line_follow",
        "stop_line_follow",
    ]
    assert fake_laravel.start_calls == [executable_mission()]


def test_dispense_rejects_both_boxes_zero(client: TestClient) -> None:
    response = client.post("/dispense", json={"box1": 0, "box2": 0})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"box1": -1, "box2": 0},
        {"box1": 0, "box2": -1},
    ],
)
def test_dispense_rejects_negative_quantities(
    client: TestClient,
    payload: dict[str, int],
) -> None:
    response = client.post("/dispense", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"box1": 11, "box2": 0},
        {"box1": 0, "box2": 11},
    ],
)
def test_dispense_rejects_quantities_above_ten(
    client: TestClient,
    payload: dict[str, int],
) -> None:
    response = client.post("/dispense", json=payload)

    assert response.status_code == 422


def test_valid_box_one_request(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/dispense", json={"box1": 2, "box2": 0})

    assert response.status_code == 200
    assert response.json()["requested"] == {"box1": 2, "box2": 0}
    assert response.json()["results"]["box1"]["dispensed_pills"] == 2
    assert fake_hardware.dispense_calls == [(1, 2)]


def test_valid_box_two_request(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/dispense", json={"box1": 0, "box2": 3})

    assert response.status_code == 200
    assert response.json()["requested"] == {"box1": 0, "box2": 3}
    assert response.json()["results"]["box2"]["dispensed_pills"] == 3
    assert fake_hardware.dispense_calls == [(2, 3)]


def test_combined_request_dispenses_box_one_first(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/dispense", json={"box1": 1, "box2": 2})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert fake_hardware.dispense_calls == [(1, 1), (2, 2)]


def test_dispense_hardware_unavailable_sends_no_command(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    client.app.state.hardware_connected = False

    response = client.post("/dispense", json={"box1": 1, "box2": 0})

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "HARDWARE_UNAVAILABLE"}}
    assert fake_hardware.dispense_calls == []


@pytest.mark.parametrize("amount_ml", [0, -1, 1001])
def test_water_dispense_rejects_invalid_amount(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    amount_ml: int,
) -> None:
    response = client.post("/water/dispense", json={"amount_ml": amount_ml})

    assert response.status_code == 422
    assert fake_hardware.water_calls == []


def test_water_conversion_uses_configured_flow_rate() -> None:
    assert calculate_water_duration_ms(100, 50.0) == 2000


def test_water_conversion_requires_physical_calibration() -> None:
    with pytest.raises(WaterCalibrationError):
        calculate_water_duration_ms(100, 0)


def test_water_endpoint_requires_physical_calibration(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    client.app.state.hardware_settings = replace(
        client.app.state.hardware_settings,
        water_flow_ml_per_second=0,
    )

    response = client.post("/water/dispense", json={"amount_ml": 100})

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "WATER_FLOW_NOT_CALIBRATED"}
    }
    assert fake_hardware.water_calls == []


def test_water_dispense_uses_calibrated_duration(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/water/dispense", json={"amount_ml": 100})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "requested_amount_ml": 100,
        "delivery_basis": "calibrated_time",
        "calibration_ml_per_second": 50.0,
        "duration_ms": 2000,
    }
    assert fake_hardware.water_calls == [2000]


def test_water_hardware_unavailable_sends_no_command(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    client.app.state.hardware_connected = False

    response = client.post("/water/dispense", json={"amount_ml": 100})

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "HARDWARE_UNAVAILABLE"}}
    assert fake_hardware.water_calls == []


def test_hardware_error_returns_service_unavailable(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    fake_hardware.hardware_error = SerialConnectionError(
        "SERIAL_DEVICE_NOT_FOUND|PORT=/dev/serial/example"
    )

    response = client.get("/ping")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "HARDWARE_COMMUNICATION_FAILED"}
    }
    assert "/dev/serial/example" not in response.text


@pytest.mark.parametrize(
    ("endpoint", "movement", "acknowledgement"),
    [
        ("/movement/forward", "forward", "ACK|FORWARD"),
        ("/movement/backward", "backward", "ACK|BACKWARD"),
        ("/movement/left", "left", "ACK|LEFT"),
        ("/movement/right", "right", "ACK|RIGHT"),
        ("/movement/stop", "stop", "ACK|STOP"),
        (
            "/movement/manual/forward",
            "manual-forward",
            "ACK|MANUAL_FORWARD",
        ),
        (
            "/movement/manual/backward",
            "manual-backward",
            "ACK|MANUAL_BACKWARD",
        ),
        ("/movement/manual/left", "manual-left", "ACK|MANUAL_LEFT"),
        ("/movement/manual/right", "manual-right", "ACK|MANUAL_RIGHT"),
        (
            "/movement/manual/forward-left",
            "manual-forward-left",
            "ACK|MANUAL_FORWARD_LEFT",
        ),
        (
            "/movement/manual/forward-right",
            "manual-forward-right",
            "ACK|MANUAL_FORWARD_RIGHT",
        ),
        (
            "/movement/manual/backward-left",
            "manual-backward-left",
            "ACK|MANUAL_BACKWARD_LEFT",
        ),
        (
            "/movement/manual/backward-right",
            "manual-backward-right",
            "ACK|MANUAL_BACKWARD_RIGHT",
        ),
        ("/movement/manual/stop", "manual-stop", "ACK|MANUAL_STOP"),
    ],
)
def test_movement_endpoint_sends_exactly_one_command(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    endpoint: str,
    movement: str,
    acknowledgement: str,
) -> None:
    response = client.post(endpoint)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "movement": movement,
        "response": acknowledgement,
    }
    assert fake_hardware.movement_calls == [movement]


def test_movement_hardware_error_returns_service_unavailable(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    fake_hardware.hardware_error = SerialConnectionError(
        "SERIAL_WRITE_FAILED|PORT=/dev/serial/example"
    )

    response = client.post("/movement/forward")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "HARDWARE_COMMUNICATION_FAILED"}
    }
    assert fake_hardware.movement_calls == []
    assert "/dev/serial/example" not in response.text


@pytest.mark.parametrize(
    ("http_method", "endpoint", "controller_method", "response_body"),
    [
        (
            "GET",
            "/line/sensors",
            "get_line_reading",
            {
                "success": True,
                "reading": "LINE|O1=1|O2=1|O3=0|O4=1|O5=1|PATTERN=11011",
            },
        ),
        (
            "GET",
            "/line/status",
            "get_line_status",
            {
                "success": True,
                "status": (
                    "LINE_STATUS|MODE=FOLLOWING|STATE=SEARCHING_LEFT|PATTERN=11111"
                ),
            },
        ),
        (
            "POST",
            "/line/start",
            "start_line_follow",
            {"success": True, "response": "ACK|LINE_FOLLOW_STARTED"},
        ),
        (
            "POST",
            "/line/stop",
            "stop_line_follow",
            {"success": True, "response": "ACK|LINE_FOLLOW_STOPPED"},
        ),
    ],
)
def test_line_endpoint_invokes_exactly_one_controller_method(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    http_method: str,
    endpoint: str,
    controller_method: str,
    response_body: dict[str, object],
) -> None:
    response = client.request(http_method, endpoint)

    assert response.status_code == 200
    assert response.json() == response_body
    assert fake_hardware.line_calls == [controller_method]


def test_line_hardware_error_returns_service_unavailable(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    fake_hardware.hardware_error = SerialConnectionError(
        "SERIAL_READ_FAILED|PORT=/dev/serial/example"
    )

    response = client.post("/line/start")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "HARDWARE_COMMUNICATION_FAILED"}
    }
    assert fake_hardware.line_calls == []
    assert "/dev/serial/example" not in response.text


@pytest.mark.parametrize(
    ("direction", "acknowledgement"),
    [
        ("left", "ACK|INTERSECTION_LEFT_STARTED"),
        ("right", "ACK|INTERSECTION_RIGHT_STARTED"),
        ("straight", "ACK|INTERSECTION_STRAIGHT_STARTED"),
    ],
)
def test_navigation_endpoint_invokes_exactly_one_controller_method(
    client: TestClient,
    fake_hardware: FakeHardwareController,
    direction: str,
    acknowledgement: str,
) -> None:
    response = client.post(f"/navigation/intersection/{direction}")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "direction": direction,
        "response": acknowledgement,
    }
    assert fake_hardware.navigation_calls == [direction]


def test_u_turn_endpoint_invokes_exactly_one_controller_method(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    response = client.post("/navigation/u-turn")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "direction": "u-turn",
        "response": "ACK|U_TURN_STARTED",
    }
    assert fake_hardware.navigation_calls == ["u-turn"]


def test_navigation_hardware_error_returns_service_unavailable(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    fake_hardware.hardware_error = SerialConnectionError(
        "SERIAL_READ_FAILED|PORT=/dev/serial/example"
    )

    response = client.post("/navigation/intersection/left")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "HARDWARE_COMMUNICATION_FAILED"}
    }
    assert fake_hardware.navigation_calls == []
    assert "/dev/serial/example" not in response.text


def test_u_turn_hardware_error_returns_service_unavailable(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    fake_hardware.hardware_error = SerialConnectionError(
        "SERIAL_READ_FAILED|PORT=/dev/serial/example"
    )

    response = client.post("/navigation/u-turn")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "HARDWARE_COMMUNICATION_FAILED"}
    }
    assert fake_hardware.navigation_calls == []
    assert "/dev/serial/example" not in response.text


def test_navigation_unexpected_error_returns_safe_internal_error(
    client: TestClient,
    fake_hardware: FakeHardwareController,
) -> None:
    fake_hardware.hardware_error = RuntimeError("private stack detail")

    response = client.post("/navigation/intersection/right")

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "INTERNAL_ERROR"}}
    assert "private stack detail" not in response.text
