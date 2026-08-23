"""Unit tests for ESP32-only manual movement commands."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import datetime
from queue import Empty, Queue
from typing import Iterator

import pytest

from raspberry_controller.hardware_controller import (
    DispenseError,
    HardwareControllerError,
    RobotHardwareController,
    SerialController,
    UnexpectedSerialResponse,
)
from raspberry_controller.services.laravel_api_client import ClaimedMission
from raspberry_controller.services.mission_executor import (
    MissionExecutionState,
    MissionExecutor,
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

    @contextmanager
    def response_transaction(self) -> Iterator[None]:
        yield

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


class ScriptedArduinoSerialController(RecordingSerialController):
    """Supply each UNO protocol response or failure in order."""

    def __init__(self, responses: list[str | HardwareControllerError]) -> None:
        super().__init__()
        self._scripted_responses = list(responses)

    def wait_for_response(
        self,
        expected: str | Sequence[str],
        *,
        validator: Callable[[str], bool] | None = None,
        response_prefix: str | None = None,
        overall_timeout: float | None = None,
    ) -> str:
        self.expected_responses.append(expected)
        response = self._scripted_responses.pop(0)
        if isinstance(response, HardwareControllerError):
            raise response
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


def test_set_rtc_uses_machine_readable_contract_and_confirmed_readback() -> None:
    requested = datetime(2026, 8, 23, 13, 30, 0)
    command = "SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30|SEC=00"
    response = "ACK|SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30|SEC=00"
    esp32 = RecordingSerialController({command: response})
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.set_rtc_datetime(requested) == requested
    assert esp32.commands == [command]


def test_set_rtc_rejects_a_mismatched_readback_confirmation() -> None:
    requested = datetime(2026, 8, 23, 13, 30, 0)
    command = "SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30|SEC=00"
    response = "ACK|SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30|SEC=01"
    controller = RobotHardwareController(
        esp32=RecordingSerialController({command: response}),  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(UnexpectedSerialResponse, match="RTC_SET_CONFIRMATION_MISMATCH"):
        controller.set_rtc_datetime(requested)


@pytest.mark.parametrize(
    "rtc_datetime",
    [
        datetime(1999, 12, 31, 23, 59, 59),
        datetime.fromisoformat("2026-08-23T13:30:00+00:00"),
    ],
)
def test_set_rtc_rejects_values_outside_its_wall_clock_contract(
    rtc_datetime: datetime,
) -> None:
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError):
        controller.set_rtc_datetime(rtc_datetime)


def test_hand_state_and_lcd_workflow_use_esp32_machine_readable_commands() -> None:
    esp32 = RecordingSerialController(
        {
            "GET_HAND": "HAND|DETECTED",
            "LCD|STATE=HAND_WAITING": "ACK|LCD|STATE=HAND_WAITING",
        }
    )
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.get_hand_status() == "HAND|DETECTED"
    assert (
        controller.show_medicine_workflow_status("HAND_WAITING")
        == "ACK|LCD|STATE=HAND_WAITING"
    )
    assert esp32.commands == ["GET_HAND", "LCD|STATE=HAND_WAITING"]


def test_pickup_countdown_uses_one_bounded_structured_lcd_command() -> None:
    command = "LCD|STATE=PICKUP_WAITING|SECONDS=30"
    esp32 = RecordingSerialController({command: f"ACK|{command}"})
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.show_pickup_countdown(30) == f"ACK|{command}"
    assert esp32.commands == [command]

    with pytest.raises(ValueError):
        controller.show_pickup_countdown(31)


def test_hand_response_is_not_misrouted_as_an_async_navigation_event() -> None:
    assert SerialController._is_async_line("HAND|DETECTED") is False
    assert SerialController._is_async_line("IR|HAND_DETECTED") is True


def test_water_level_uses_the_existing_esp32_connection_and_strict_contract() -> None:
    esp32 = RecordingSerialController(
        {
            "GET_WATER_LEVEL": (
                "WATER_LEVEL|DISTANCE_CM=7.3|PERCENT=68|STATUS=OK"
            ),
        }
    )
    uno = RecordingSerialController()
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=uno,  # type: ignore[arg-type]
    )

    assert controller.get_water_level() == {
        "distance_cm": 7.3,
        "percent": 68,
        "status": "OK",
    }
    assert esp32.commands == ["GET_WATER_LEVEL"]
    assert uno.commands == []
    assert SerialController._is_async_line(
        "WATER_LEVEL|DISTANCE_CM=7.3|PERCENT=68|STATUS=OK"
    ) is False


def test_water_level_sensor_error_is_structured_without_a_fake_percentage() -> None:
    assert RobotHardwareController.parse_water_level(
        "WATER_LEVEL|DISTANCE_CM=NA|PERCENT=NA|STATUS=SENSOR_ERROR"
    ) == {
        "distance_cm": None,
        "percent": None,
        "status": "SENSOR_ERROR",
    }


def test_manual_pump_reuses_existing_esp32_commands_and_stops_after_timed_run() -> None:
    esp32 = RecordingSerialController(
        {
            "O": "ACK|PUMP|STATE=ON",
            "X": "ACK|PUMP|STATE=OFF",
        }
    )
    controller = RobotHardwareController(
        esp32=esp32,  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    controller.start_manual_pump()
    controller.stop_manual_pump()
    assert controller.run_manual_pump(5) == {"ran_seconds": 5}

    assert esp32.commands == ["O", "X", "WATER_DISPENSE|MS=5000", "X"]


@pytest.mark.parametrize("seconds", [0, -1, 31])
def test_manual_pump_rejects_unsafe_timed_runs(seconds: int) -> None:
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError):
        controller.run_manual_pump(seconds)


def test_manual_pump_attempts_a_final_stop_after_a_timed_run_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )
    stopped: list[bool] = []

    def fail_duration_command(_duration_ms: int) -> dict[str, int]:
        raise HardwareControllerError("TIMED_PUMP_FAILED")

    def record_final_stop() -> None:
        stopped.append(True)

    monkeypatch.setattr(controller, "dispense_water", fail_duration_command)
    monkeypatch.setattr(controller, "stop_manual_pump", record_final_stop)

    with pytest.raises(HardwareControllerError, match="TIMED_PUMP_FAILED"):
        controller.run_manual_pump(5)

    assert stopped == [True]


@pytest.mark.parametrize(
    "response",
    [
        "WATER_LEVEL|DISTANCE_CM=7.3|PERCENT=101|STATUS=OK",
        "WATER_LEVEL|DISTANCE_CM=NA|PERCENT=0|STATUS=SENSOR_ERROR",
        "WATER_LEVEL|DISTANCE_CM=7.3|PERCENT=68|STATUS=UNKNOWN",
    ],
)
def test_water_level_parser_rejects_invalid_structured_responses(response: str) -> None:
    with pytest.raises(ValueError):
        RobotHardwareController.parse_water_level(response)


def test_real_uno_disk_status_line_is_not_misrouted_as_async_telemetry() -> None:
    response = (
        "DISK_STATUS|DISK1_CALIBRATED=0|DISK1_SLOT=0|"
        "DISK2_CALIBRATED=0|DISK2_SLOT=0"
    )

    assert SerialController._is_async_line(response) is False
    assert RobotHardwareController.parse_disk_status(response) == {
        "disk1": {"calibrated": False, "slot": 0},
        "disk2": {"calibrated": False, "slot": 0},
    }


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


@pytest.mark.parametrize(
    "response",
    [
        "ACK|SET_RTC|YYYY=2026|MM=13|DD=23|HH=13|MIN=30|SEC=00",
        "ACK|SET_RTC|YYYY=2026|MM=02|DD=29|HH=13|MIN=30|SEC=00",
        "ACK|SET_RTC|YYYY=2024|MM=02|DD=30|HH=13|MIN=30|SEC=00",
        "ACK|SET_RTC|YYYY=2026|MM=08|DD=23|HH=24|MIN=30|SEC=00",
        "ACK|SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=60|SEC=00",
        "ACK|SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30|SEC=60",
        "ACK|SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30",
    ],
)
def test_set_rtc_parser_rejects_invalid_or_malformed_confirmations(
    response: str,
) -> None:
    with pytest.raises(ValueError):
        RobotHardwareController.parse_rtc_set_response(response)


def test_set_rtc_parser_accepts_a_valid_leap_day() -> None:
    response = "ACK|SET_RTC|YYYY=2024|MM=02|DD=29|HH=23|MIN=59|SEC=59"

    assert RobotHardwareController.parse_rtc_set_response(response) == datetime(
        2024, 2, 29, 23, 59, 59
    )


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


def test_dispense_preserves_exact_ack_done_contract_per_confirmed_pill() -> None:
    arduino = ScriptedArduinoSerialController(
        [
            "ACK|DISPENSE_1",
            "DONE|DISPENSE_1",
            "ACK|DISPENSE_1",
            "DONE|DISPENSE_1",
        ]
    )
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=arduino,  # type: ignore[arg-type]
    )

    result = controller.dispense(1, 2)

    assert result == {
        "box_number": 1,
        "requested_pills": 2,
        "dispensed_pills": 2,
    }
    assert arduino.commands == ["DISPENSE_1", "DISPENSE_1"]
    assert arduino.expected_responses == [
        "ACK|DISPENSE_1",
        "DONE|DISPENSE_1",
        "ACK|DISPENSE_1",
        "DONE|DISPENSE_1",
    ]


def test_dispense_sensor_timeout_is_immediate_and_preserves_partial_count() -> None:
    arduino = ScriptedArduinoSerialController(
        [
            "ACK|DISPENSE_1",
            "DONE|DISPENSE_1",
            "ACK|DISPENSE_1",
            "DONE|DISPENSE_1",
            "ACK|DISPENSE_1",
            UnexpectedSerialResponse(
                "UNEXPECTED_RESPONSE|RECEIVED=ERROR|DISPENSE_1|CODE=PILL_TIMEOUT"
            ),
        ]
    )
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=arduino,  # type: ignore[arg-type]
    )

    with pytest.raises(
        DispenseError,
        match=r"DISPENSE_FAILED\|BOX=1\|COMPLETED=2\|STAGE=DONE\|CAUSE=PILL_TIMEOUT",
    ):
        controller.dispense(1, 3)

    assert arduino.commands == ["DISPENSE_1", "DISPENSE_1", "DISPENSE_1"]


def test_dispense_sensor_stuck_is_immediate_without_completed_pill() -> None:
    arduino = ScriptedArduinoSerialController(
        [
            "ACK|DISPENSE_2",
            UnexpectedSerialResponse(
                "UNEXPECTED_RESPONSE|RECEIVED=ERROR|DISPENSE_2|CODE=SENSOR_STUCK"
            ),
        ]
    )
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=arduino,  # type: ignore[arg-type]
    )

    with pytest.raises(
        DispenseError,
        match=r"DISPENSE_FAILED\|BOX=2\|COMPLETED=0\|STAGE=DONE\|CAUSE=SENSOR_STUCK",
    ):
        controller.dispense(2, 1)


def test_disk_status_and_manual_zero_use_the_existing_uno_connection() -> None:
    uno = RecordingSerialController(
        {
            "GET_DISK_STATUS": (
                "DISK_STATUS|DISK1_CALIBRATED=1|DISK1_SLOT=0|"
                "DISK2_CALIBRATED=1|DISK2_SLOT=7"
            ),
            "SET_SLOT_ZERO_1": "ACK|SET_SLOT_ZERO_1",
        }
    )
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=uno,  # type: ignore[arg-type]
    )

    assert controller.get_disk_status() == {
        "disk1": {"calibrated": True, "slot": 0},
        "disk2": {"calibrated": True, "slot": 7},
    }
    assert controller.set_slot_zero(1) == {"calibrated": True, "slot": 0}
    assert uno.commands == [
        "GET_DISK_STATUS",
        "SET_SLOT_ZERO_1",
        "GET_DISK_STATUS",
    ]


@pytest.mark.parametrize("box_number", [1, 2])
def test_slot_zero_uses_the_matching_uno_command(box_number: int) -> None:
    command = f"SET_SLOT_ZERO_{box_number}"
    uno = RecordingSerialController(
        {
            command: f"ACK|{command}",
            "GET_DISK_STATUS": (
                "DISK_STATUS|DISK1_CALIBRATED=1|DISK1_SLOT=0|"
                "DISK2_CALIBRATED=1|DISK2_SLOT=0"
            ),
        }
    )
    controller = RobotHardwareController(
        esp32=RecordingSerialController(),  # type: ignore[arg-type]
        arduino_uno=uno,  # type: ignore[arg-type]
    )

    assert controller.set_slot_zero(box_number)["calibrated"] is True
    assert uno.commands[0] == command


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
        ("manual_forward", "MANUAL_FORWARD", "ACK|MANUAL_FORWARD"),
        ("manual_backward", "MANUAL_BACKWARD", "ACK|MANUAL_BACKWARD"),
        ("manual_left", "MANUAL_LEFT", "ACK|MANUAL_LEFT"),
        ("manual_right", "MANUAL_RIGHT", "ACK|MANUAL_RIGHT"),
        (
            "manual_forward_left",
            "MANUAL_FORWARD_LEFT",
            "ACK|MANUAL_FORWARD_LEFT",
        ),
        (
            "manual_forward_right",
            "MANUAL_FORWARD_RIGHT",
            "ACK|MANUAL_FORWARD_RIGHT",
        ),
        (
            "manual_backward_left",
            "MANUAL_BACKWARD_LEFT",
            "ACK|MANUAL_BACKWARD_LEFT",
        ),
        (
            "manual_backward_right",
            "MANUAL_BACKWARD_RIGHT",
            "ACK|MANUAL_BACKWARD_RIGHT",
        ),
        ("manual_stop", "MANUAL_STOP", "ACK|MANUAL_STOP"),
    ],
)
def test_manual_drive_uses_only_esp32_and_validates_exact_ack(
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
        self.readline_threads: list[str] = []

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        self.readline_threads.append(threading.current_thread().name)
        return self.responses.pop(0) if self.responses else b""

    def close(self) -> None:
        self.is_open = False


class CommandResponsiveSerialConnection(FakeSerialConnection):
    """Release scripted ESP32 lines only after their command is written."""

    def __init__(self, responses: dict[bytes, list[bytes]]) -> None:
        super().__init__([])
        self.command_responses = responses
        self.pending_lines: Queue[bytes] = Queue()

    def write(self, payload: bytes) -> None:
        super().write(payload)
        for line in self.command_responses.get(payload, []):
            self.pending_lines.put(line)

    def readline(self) -> bytes:
        self.readline_threads.append(threading.current_thread().name)
        try:
            return self.pending_lines.get(timeout=self.timeout)
        except Empty:
            return b""


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
    assert controller.get_esp32_event(0.05) == (
        "EVENT|INTERSECTION|PATTERN=00000"
    )


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
    assert controller.get_esp32_event(0.05) == (
        "LINE|RECOVERY|STATE=GYRO_SEARCH|PATTERN=11111|"
        "ERROR=0.00|ANGLE=-22.5|CYCLE=1"
    )


def test_one_persistent_reader_dispatches_event_and_command_response() -> None:
    connection = FakeSerialConnection(
        [
            b"EVENT|INTERSECTION|PATTERN=00000\n",
            b"ACK|INTERSECTION_LEFT_STARTED\n",
        ]
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.05)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.intersection_left() == "ACK|INTERSECTION_LEFT_STARTED"
    reader_thread = esp32._reader_thread
    esp32._ensure_reader_started()

    assert reader_thread is not None
    assert esp32._reader_thread is reader_thread
    assert controller.get_esp32_event(0.05) == (
        "EVENT|INTERSECTION|PATTERN=00000"
    )
    assert set(connection.readline_threads) == {"serial-reader-mock"}
    esp32.close()


def test_line_follow_ack_then_intersection_event_are_routed_independently() -> None:
    connection = CommandResponsiveSerialConnection(
        {
            b"START_LINE_FOLLOW\n": [
                b"ACK|LINE_FOLLOW_STARTED\n"
                b"EVENT|INTERSECTION|PATTERN=00000\n",
            ],
            b"STOP_LINE_FOLLOW\n": [b"ACK|LINE_FOLLOW_STOPPED\n"],
        }
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.1)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.start_line_follow() == "ACK|LINE_FOLLOW_STARTED"
    assert controller.get_esp32_event(0.1) == (
        "EVENT|INTERSECTION|PATTERN=00000"
    )
    assert controller.stop_line_follow() == "ACK|LINE_FOLLOW_STOPPED"
    assert connection.writes == [
        b"START_LINE_FOLLOW\n",
        b"STOP_LINE_FOLLOW\n",
    ]
    assert set(connection.readline_threads) == {"serial-reader-mock"}
    esp32.close()


def test_fragmented_line_follow_ack_is_buffered_until_newline() -> None:
    connection = CommandResponsiveSerialConnection(
        {
            b"START_LINE_FOLLOW\n": [
                b"ACK|LINE_FOLLOW_",
                b"STARTED\n",
            ],
            b"STOP_LINE_FOLLOW\n": [
                b"ACK|LINE_FOLLOW_",
                b"STOPPED\n",
            ],
        }
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.1)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )

    assert controller.start_line_follow() == "ACK|LINE_FOLLOW_STARTED"
    assert controller.stop_line_follow() == "ACK|LINE_FOLLOW_STOPPED"
    assert controller.get_esp32_event(0.01) is None
    esp32.close()


def test_mission_executor_start_preserves_immediate_intersection_event() -> None:
    connection = CommandResponsiveSerialConnection(
        {
            b"START_LINE_FOLLOW\n": [
                b"ACK|LINE_FOLLOW_STARTED\n"
                b"EVENT|INTERSECTION|PATTERN=00000\n",
            ],
        }
    )
    esp32 = SerialController("mock", 115200, startup_delay=0, read_timeout=0.1)
    esp32._connection = connection
    controller = RobotHardwareController(
        esp32=esp32,
        arduino_uno=RecordingSerialController(),  # type: ignore[arg-type]
    )
    started_missions: list[int] = []
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=controller.start_line_follow,
        stop_line_follow=controller.stop_line_follow,
            mark_mission_in_progress=lambda mission: started_missions.append(
                mission.id
            ),
            require_home_readiness=False,
        )
    mission = ClaimedMission(
        id=42,
        room_id=1,
        medicine_id=2,
        quantity=1,
        room_number="1",
        dispenser_box=1,
        schedule_claimed_at="2026-08-12T09:00:00+00:00",
    )

    assert executor.accept(mission) is True
    outcome = executor.start_ready_mission()

    assert outcome.success is True
    assert executor.state is MissionExecutionState.GOING_TO_ROOM
    assert started_missions == [42]
    assert controller.get_esp32_event(0.1) == (
        "EVENT|INTERSECTION|PATTERN=00000"
    )
    assert connection.writes == [b"START_LINE_FOLLOW\n"]
    esp32.close()


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
