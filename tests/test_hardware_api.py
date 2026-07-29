"""API tests that replace all real serial hardware with an in-memory fake."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from raspberry_controller.api import HardwareSettings, create_app
from raspberry_controller.hardware_controller import SerialConnectionError


class FakeHardwareController:
    """Record API-to-hardware calls without opening serial devices."""

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.dispense_calls: list[tuple[int, int]] = []
        self.movement_calls: list[str] = []
        self.line_calls: list[str] = []
        self.hardware_error: Exception | None = None

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
        return self._record_line_call(
            "start_line_follow",
            "ACK|LINE_FOLLOW_STARTED",
        )

    def stop_line_follow(self) -> str:
        return self._record_line_call(
            "stop_line_follow",
            "ACK|LINE_FOLLOW_STOPPED",
        )

    def _record_line_call(self, method: str, response: str) -> str:
        self._raise_hardware_error()
        self.line_calls.append(method)
        return response

    def _raise_hardware_error(self) -> None:
        if self.hardware_error is not None:
            raise self.hardware_error


@pytest.fixture
def fake_hardware() -> FakeHardwareController:
    return FakeHardwareController()


@pytest.fixture
def client(fake_hardware: FakeHardwareController) -> Iterator[TestClient]:
    def fake_factory(settings: HardwareSettings) -> FakeHardwareController:
        assert settings.esp32_port.startswith("/dev/serial/by-id/")
        assert settings.arduino_port.startswith("/dev/serial/by-id/")
        return fake_hardware

    application = create_app(controller_factory=fake_factory)
    with TestClient(application) as test_client:
        yield test_client

    assert fake_hardware.closed is True


def test_root_lists_api_information(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Autonomous Medicine Dispensing Robot Hardware API"
    assert body["version"] == "1.0.0"
    assert "/dispense" in body["endpoints"]
    assert "/movement/stop" in body["endpoints"]
    assert "/line/start" in body["endpoints"]
    assert "/line/stop" in body["endpoints"]


def test_health_reports_connected_hardware(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "running", "hardware_connected": True}


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
