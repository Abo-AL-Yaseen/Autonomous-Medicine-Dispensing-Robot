"""Unit tests for ESP32-only manual movement commands."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

import pytest

from raspberry_controller.hardware_controller import (
    HardwareControllerError,
    RobotHardwareController,
    SerialController,
    UnexpectedSerialResponse,
)


class RecordingSerialController:
    """Record commands and expected responses without using pyserial."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.commands: list[str] = []
        self.expected_responses: list[str | Sequence[str]] = []
        self.responses = responses or {}
        self.read_timeout = 0.05

    def send_command(self, command: str) -> None:
        self.commands.append(command)

    def wait_for_response(
        self,
        expected: str | Sequence[str],
        *,
        validator: Callable[[str], bool] | None = None,
        response_prefix: str | None = None,
        overall_timeout: float | None = None,
    ) -> str:
        self.expected_responses.append(expected)
        response = self.responses.get(self.commands[-1])
        if response is None:
            response = expected if isinstance(expected, str) else expected[0]
        if validator is not None:
            assert validator(response)
        if response_prefix is not None:
            assert response.startswith(response_prefix)
        return response


def test_get_rtc_uses_machine_readable_contract() -> None:
    response = "RTC|YYYY=2026|MM=08|DD=09|HH=20|MIN=30|SEC=00"
    esp32 = RecordingSerialController({"GET_RTC": response})
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    rtc_datetime = controller.get_rtc_datetime()

    assert rtc_datetime == datetime(2026, 8, 9, 20, 30, 0)
    assert rtc_datetime.tzinfo is None
    assert esp32.commands == ["GET_RTC"]


@pytest.mark.parametrize(
    "response",
    [
        "RTC|YYYY=2026|MM=08|DD=09|HH=20|MIN=30",
        "RTC|YYYY=2026|MM=13|DD=09|HH=20|MIN=30|SEC=00",
        "RTC|YYYY=2026|MM=08|DD=09|HH=20|MIN=xx|SEC=00",
        "RTC Time: 2026/08/09 20:30:00",
    ],
)
def test_malformed_rtc_response_is_rejected(response: str) -> None:
    connection = FakeSerialConnection([(response + "\n").encode("ascii")])
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(HardwareControllerError):
        controller.get_rtc_datetime()

    assert connection.writes == [b"GET_RTC\n"]


def test_water_dispense_sends_one_bounded_duration_command() -> None:
    connection = FakeSerialConnection(
        [
            b"ACK|WATER|DURATION_MS=2000\n",
            b"DONE|WATER|DURATION_MS=2000\n",
        ]
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.dispense_water(2000) == {"duration_ms": 2000}
    assert connection.writes == [b"WATER_DISPENSE|MS=2000\n"]


@pytest.mark.parametrize(
    ("method_name", "command", "acknowledgement"),
    [
        ("forward", "F", "ACK|FORWARD"),
        ("backward", "B", "ACK|BACKWARD"),
        ("turn_left", "L", "ACK|LEFT"),
        ("turn_right", "R", "ACK|RIGHT"),
        ("stop", "S", "ACK|STOP"),
    ],
)
def test_movement_uses_only_esp32(
    method_name: str,
    command: str,
    acknowledgement: str,
) -> None:
    esp32 = RecordingSerialController()
    arduino_uno = RecordingSerialController()
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=arduino_uno,  # type: ignore[arg-type]
    )

    response = getattr(controller, method_name)()

    assert response == acknowledgement
    assert esp32.commands == [command]
    assert esp32.expected_responses == [acknowledgement]
    assert arduino_uno.commands == []
    assert arduino_uno.expected_responses == []


@pytest.mark.parametrize(
    ("method_name", "command", "acknowledgement"),
    [
        (
            "intersection_left",
            "INTERSECTION_LEFT",
            "ACK|INTERSECTION_LEFT_STARTED",
        ),
        (
            "intersection_right",
            "INTERSECTION_RIGHT",
            "ACK|INTERSECTION_RIGHT_STARTED",
        ),
        (
            "intersection_straight",
            "INTERSECTION_STRAIGHT",
            "ACK|INTERSECTION_STRAIGHT_STARTED",
        ),
        (
            "u_turn",
            "U_TURN",
            "ACK|U_TURN_STARTED",
        ),
    ],
)
def test_navigation_uses_only_esp32_and_validates_exact_ack(
    method_name: str,
    command: str,
    acknowledgement: str,
) -> None:
    esp32 = RecordingSerialController({command: acknowledgement})
    arduino_uno = RecordingSerialController()
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=arduino_uno,  # type: ignore[arg-type]
    )

    assert getattr(controller, method_name)() == acknowledgement
    assert esp32.commands == [command]
    assert esp32.expected_responses == [acknowledgement]
    assert arduino_uno.commands == []
    assert arduino_uno.expected_responses == []


@pytest.mark.parametrize(
    ("method_name", "command", "expected", "response"),
    [
        (
            "get_line_reading",
            "GET_LINE",
            "VALID_LINE_READING",
            "LINE|O1=1|O2=1|O3=0|O4=1|O5=1|PATTERN=11011",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=FOLLOWING|STATE=SEARCHING_LEFT|PATTERN=11111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=FOLLOWING|STATE=SEARCHING_RIGHT|PATTERN=11111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=TURNING_LEFT|PATTERN=00000",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=CENTERING_LEFT|PATTERN=00000",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=CENTERING_RIGHT|PATTERN=00000",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=PIVOTING_LEFT|PATTERN=00000",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=PIVOTING_RIGHT|PATTERN=00000",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=PIVOT_SEARCH_LEFT|PATTERN=11011",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=PIVOT_SEARCH_RIGHT|PATTERN=11111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=SENSOR_ALIGN_LEFT|PATTERN=01111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=SENSOR_ALIGN_RIGHT|PATTERN=11110",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=LOCKING_LINE_LEFT|PATTERN=10111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=LOCKING_LINE_RIGHT|PATTERN=11101",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=REACQUIRING_LEFT|PATTERN=11111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=REACQUIRING_RIGHT|PATTERN=00000",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=ACQUIRING_RIGHT|PATTERN=11101",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=UTURN_PIVOT_SEARCH|PATTERN=11011",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=UTURN_SENSOR_ALIGN|PATTERN=01111",
        ),
        (
            "get_line_status",
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            "LINE_STATUS|MODE=NAVIGATION|STATE=UTURN_LINE_LOCK|PATTERN=11011",
        ),
        (
            "start_line_follow",
            "START_LINE_FOLLOW",
            "ACK|LINE_FOLLOW_STARTED",
            "ACK|LINE_FOLLOW_STARTED",
        ),
        (
            "stop_line_follow",
            "STOP_LINE_FOLLOW",
            "ACK|LINE_FOLLOW_STOPPED",
            "ACK|LINE_FOLLOW_STOPPED",
        ),
    ],
)
def test_line_commands_use_only_esp32_and_validate_exact_response(
    method_name: str,
    command: str,
    expected: str,
    response: str,
) -> None:
    esp32 = RecordingSerialController({command: response})
    arduino_uno = RecordingSerialController()
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=arduino_uno,  # type: ignore[arg-type]
    )

    assert getattr(controller, method_name)() == response
    assert esp32.commands == [command]
    assert esp32.expected_responses == [expected]
    assert arduino_uno.commands == []
    assert arduino_uno.expected_responses == []


class FakeSerialConnection:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.writes: list[bytes] = []
        self.is_open = True
        self.timeout = 0.01

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.responses.pop(0) if self.responses else b""


def test_async_line_event_is_skipped_before_valid_response() -> None:
    connection = FakeSerialConnection(
        [
            b"EVENT|INTERSECTION|PATTERN=00000\n",
            b"LINE|O1=1|O2=1|O3=0|O4=1|O5=1|PATTERN=11011\n",
        ]
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.get_line_reading().endswith("PATTERN=11011")
    assert connection.writes == [b"GET_LINE\n"]


def test_async_line_recovery_diagnostic_is_skipped_before_line_reading() -> None:
    connection = FakeSerialConnection(
        [
            (
                b"LINE|RECOVERY|STATE=GYRO_SEARCH|PATTERN=11111|"
                b"ERROR=0.00|ANGLE=-22.5|CYCLE=1\n"
            ),
            b"LINE|O1=1|O2=1|O3=0|O4=1|O5=1|PATTERN=11011\n",
        ]
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.get_line_reading().endswith("PATTERN=11011")
    assert connection.writes == [b"GET_LINE\n"]


def test_malformed_line_response_is_rejected() -> None:
    connection = FakeSerialConnection(
        [b"LINE|O1=1|O2=1|O3=0|O4=1|O5=1|PATTERN=11111\n"]
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(UnexpectedSerialResponse):
        controller.get_line_reading()


def test_malformed_navigation_acknowledgement_is_rejected() -> None:
    connection = FakeSerialConnection([b"ACK|INTERSECTION_LEFT\n"])
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(UnexpectedSerialResponse):
        controller.intersection_left()

    assert connection.writes == [b"INTERSECTION_LEFT\n"]


def test_malformed_u_turn_acknowledgement_is_rejected() -> None:
    connection = FakeSerialConnection([b"ACK|U_TURN\n"])
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(UnexpectedSerialResponse):
        controller.u_turn()

    assert connection.writes == [b"U_TURN\n"]


@pytest.mark.parametrize(
    "event",
    [
        b"EVENT|INTERSECTION_COMPLETE|DIRECTION=LEFT|PATTERN=11011\n",
        b"EVENT|INTERSECTION_FAILED|DIRECTION=RIGHT\n",
    ],
)
def test_async_navigation_event_does_not_corrupt_later_request(event: bytes) -> None:
    connection = FakeSerialConnection([event, b"ACK|INTERSECTION_STRAIGHT_STARTED\n"])
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert (
        controller.intersection_straight()
        == "ACK|INTERSECTION_STRAIGHT_STARTED"
    )
    assert connection.writes == [b"INTERSECTION_STRAIGHT\n"]


@pytest.mark.parametrize(
    "event",
    [
        b"EVENT|U_TURN_COMPLETE|PATTERN=11011\n",
        b"EVENT|U_TURN_FAILED\n",
    ],
)
def test_async_u_turn_event_does_not_corrupt_ack(event: bytes) -> None:
    connection = FakeSerialConnection([event, b"ACK|U_TURN_STARTED\n"])
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.u_turn() == "ACK|U_TURN_STARTED"
    assert connection.writes == [b"U_TURN\n"]
