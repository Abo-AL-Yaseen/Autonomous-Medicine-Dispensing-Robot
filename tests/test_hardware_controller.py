"""Unit tests for ESP32-only manual movement commands."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from raspberry_controller.hardware_controller import RobotHardwareController


class RecordingSerialController:
    """Record commands and expected responses without using pyserial."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.expected_responses: list[str | Sequence[str]] = []

    def send_command(self, command: str) -> None:
        self.commands.append(command)

    def wait_for_response(self, expected: str | Sequence[str]) -> str:
        self.expected_responses.append(expected)
        if not isinstance(expected, str):
            return expected[0]
        return expected


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
