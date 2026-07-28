"""Unified serial controller for the robot's ESP32 and Arduino UNO."""

from __future__ import annotations

import argparse
import errno
import os
import sys
import time
from typing import Any, Sequence


ESP32_PORT = (
    "/dev/serial/by-id/"
    "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
)
ARDUINO_UNO_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"

ESP32_BAUD_RATE = 115200
ARDUINO_UNO_BAUD_RATE = 9600
ESP32_STARTUP_DELAY_SECONDS = 4.0
ARDUINO_UNO_STARTUP_DELAY_SECONDS = 2.0
DEFAULT_READ_TIMEOUT_SECONDS = 10.0
SERIAL_POLL_TIMEOUT_SECONDS = 0.25


class HardwareControllerError(RuntimeError):
    """Base error for serial hardware operations."""


class SerialConnectionError(HardwareControllerError):
    """Raised when a serial device cannot be opened or used."""


class SerialResponseTimeout(HardwareControllerError):
    """Raised when a board does not respond before the read timeout."""


class UnexpectedSerialResponse(HardwareControllerError):
    """Raised when a board returns a response outside the protocol."""


class DispenseError(HardwareControllerError):
    """Raised when a pill-dispense sequence cannot be confirmed."""


def _clean_field(value: object) -> str:
    """Keep exception details on one machine-readable line."""

    return str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")


class SerialController:
    """A reusable newline-based pyserial connection."""

    def __init__(
        self,
        port: str,
        baud_rate: int,
        startup_delay: float = ARDUINO_UNO_STARTUP_DELAY_SECONDS,
        read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> None:
        if not port:
            raise ValueError("port must not be empty")
        if baud_rate <= 0:
            raise ValueError("baud_rate must be positive")
        if startup_delay < 0:
            raise ValueError("startup_delay must not be negative")
        if read_timeout <= 0:
            raise ValueError("read_timeout must be positive")

        self.port = port
        self.baud_rate = baud_rate
        self.startup_delay = startup_delay
        self.read_timeout = read_timeout
        self._connection: Any | None = None
        self._serial_module: Any | None = None

    def open(self) -> None:
        """Open the port, wait for a possible board reset, and discard boot text."""

        if self._connection is not None and self._connection.is_open:
            return

        if not os.path.exists(self.port):
            raise SerialConnectionError(
                f"SERIAL_DEVICE_NOT_FOUND|PORT={_clean_field(self.port)}"
            )

        try:
            import serial
        except ImportError as exc:
            raise SerialConnectionError("DEPENDENCY_MISSING|PYSERIAL") from exc

        self._serial_module = serial
        try:
            connection = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=min(SERIAL_POLL_TIMEOUT_SECONDS, self.read_timeout),
                write_timeout=self.read_timeout,
            )
        except (serial.SerialException, OSError) as exc:
            error_number = getattr(exc, "errno", None)
            if isinstance(exc, PermissionError) or error_number in (
                errno.EACCES,
                errno.EPERM,
            ):
                category = "SERIAL_PERMISSION_DENIED"
            elif isinstance(exc, FileNotFoundError) or error_number == errno.ENOENT:
                category = "SERIAL_DEVICE_NOT_FOUND"
            else:
                category = "SERIAL_OPEN_FAILED"
            raise SerialConnectionError(
                f"{category}|PORT={_clean_field(self.port)}|DETAIL={_clean_field(exc)}"
            ) from exc

        self._connection = connection
        try:
            # USB serial open can reset either board and emit startup messages.
            time.sleep(self.startup_delay)
            connection.reset_input_buffer()
        except (serial.SerialException, OSError) as exc:
            try:
                self.close()
            except HardwareControllerError:
                pass
            raise SerialConnectionError(
                "SERIAL_INITIALIZATION_FAILED"
                f"|PORT={_clean_field(self.port)}|DETAIL={_clean_field(exc)}"
            ) from exc

    def close(self) -> None:
        """Close the connection if it is open."""

        connection = self._connection
        self._connection = None
        if connection is None or not connection.is_open:
            return

        try:
            connection.close()
        except self._communication_exceptions() as exc:
            raise SerialConnectionError(
                f"SERIAL_CLOSE_FAILED|PORT={_clean_field(self.port)}"
                f"|DETAIL={_clean_field(exc)}"
            ) from exc

    def send_command(self, command: str) -> None:
        """Send one ASCII command terminated by a newline."""

        connection = self._require_connection()
        normalized_command = command.strip()
        if (
            not normalized_command
            or "\r" in normalized_command
            or "\n" in normalized_command
        ):
            raise ValueError("command must be one non-empty line")

        try:
            payload = (normalized_command + "\n").encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("command must contain only ASCII characters") from exc

        try:
            connection.write(payload)
            connection.flush()
        except self._communication_exceptions() as exc:
            raise SerialConnectionError(
                f"SERIAL_WRITE_FAILED|PORT={_clean_field(self.port)}"
                f"|DETAIL={_clean_field(exc)}"
            ) from exc

    def wait_for_response(self, expected: str | Sequence[str]) -> str:
        """Scan serial lines until an expected response or overall timeout."""

        connection = self._require_connection()
        expected_responses = (expected,) if isinstance(expected, str) else tuple(expected)
        if not expected_responses:
            raise ValueError("at least one expected response is required")

        expected_text = ",".join(expected_responses)
        deadline = time.monotonic() + self.read_timeout
        last_non_empty_response: str | None = None

        while True:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                break

            # Keep each read short so asynchronous lines cannot extend the deadline.
            connection.timeout = min(SERIAL_POLL_TIMEOUT_SECONDS, remaining_time)
            try:
                raw_response = connection.readline()
            except self._communication_exceptions() as exc:
                raise SerialConnectionError(
                    f"SERIAL_READ_FAILED|PORT={_clean_field(self.port)}"
                    f"|DETAIL={_clean_field(exc)}"
                ) from exc

            if not raw_response:
                continue

            response = raw_response.decode("ascii", errors="replace").rstrip("\r\n")
            if not response:
                continue

            last_non_empty_response = response
            if response.startswith("ERROR|"):
                raise UnexpectedSerialResponse(
                    f"UNEXPECTED_RESPONSE|PORT={_clean_field(self.port)}"
                    f"|EXPECTED={_clean_field(expected_text)}"
                    f"|RECEIVED={_clean_field(response)}"
                )
            if response in expected_responses:
                return response

        timeout_message = (
            f"SERIAL_TIMEOUT|PORT={_clean_field(self.port)}"
            f"|EXPECTED={_clean_field(expected_text)}"
        )
        if last_non_empty_response is not None:
            timeout_message += (
                f"|LAST_RECEIVED={_clean_field(last_non_empty_response)}"
            )
        raise SerialResponseTimeout(timeout_message)

    def _require_connection(self) -> Any:
        if self._connection is None or not self._connection.is_open:
            raise SerialConnectionError(
                f"SERIAL_NOT_CONNECTED|PORT={_clean_field(self.port)}"
            )
        return self._connection

    def _communication_exceptions(self) -> tuple[type[BaseException], ...]:
        if self._serial_module is None:
            return (OSError,)
        return (self._serial_module.SerialException, OSError)


class RobotHardwareController:
    """Coordinate the ESP32 and Arduino UNO serial links."""

    ARDUINO_STATUS_RESPONSES = (
        "STATUS|IDLE",
        "STATUS|DISPENSING_1",
        "STATUS|DISPENSING_2",
        "STATUS|DISPENSING_BOTH",
    )

    def __init__(
        self,
        esp32: SerialController | None = None,
        arduino_uno: SerialController | None = None,
    ) -> None:
        self.esp32 = esp32 or SerialController(
            ESP32_PORT,
            ESP32_BAUD_RATE,
            startup_delay=ESP32_STARTUP_DELAY_SECONDS,
        )
        self.arduino_uno = arduino_uno or SerialController(
            ARDUINO_UNO_PORT,
            ARDUINO_UNO_BAUD_RATE,
            startup_delay=ARDUINO_UNO_STARTUP_DELAY_SECONDS,
        )

    def connect(self) -> None:
        """Connect both boards and clean up if either connection fails."""

        try:
            self.esp32.open()
            self.arduino_uno.open()
        except (HardwareControllerError, KeyboardInterrupt):
            try:
                self.close()
            except HardwareControllerError:
                pass
            raise

    def close(self) -> None:
        """Attempt to close both ports, even if one close operation fails."""

        first_error: HardwareControllerError | None = None
        for controller in (self.arduino_uno, self.esp32):
            try:
                controller.close()
            except HardwareControllerError as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def ping_all(self) -> dict[str, str]:
        """Ping both controllers and return their validated responses."""

        return {
            "ESP32": self._request(self.esp32, "PING", "ACK|PING"),
            "ARDUINO_UNO": self._request(
                self.arduino_uno,
                "PING",
                "ACK|PING",
            ),
        }

    def get_all_statuses(self) -> dict[str, str]:
        """Request and validate the current state of both controllers."""

        return {
            "ESP32": self._request(
                self.esp32,
                "GET_STATUS",
                "STATUS|IDLE",
            ),
            "ARDUINO_UNO": self._request(
                self.arduino_uno,
                "GET_STATUS",
                self.ARDUINO_STATUS_RESPONSES,
            ),
        }

    def forward(self) -> str:
        """Start continuous forward movement on the ESP32."""

        return self._request(self.esp32, "F", "ACK|FORWARD")

    def backward(self) -> str:
        """Start continuous backward movement on the ESP32."""

        return self._request(self.esp32, "B", "ACK|BACKWARD")

    def turn_left(self) -> str:
        """Request the ESP32's existing 90-degree left turn."""

        return self._request(self.esp32, "L", "ACK|LEFT")

    def turn_right(self) -> str:
        """Request the ESP32's existing 90-degree right turn."""

        return self._request(self.esp32, "R", "ACK|RIGHT")

    def stop(self) -> str:
        """Stop ESP32 motors and outputs immediately."""

        return self._request(self.esp32, "S", "ACK|STOP")

    def dispense(self, box_number: int, pill_count: int) -> dict[str, int]:
        """Dispense pills sequentially, requiring an ACK and DONE for each pill."""

        if isinstance(box_number, bool) or box_number not in (1, 2):
            raise ValueError("box_number must be 1 or 2")
        if (
            isinstance(pill_count, bool)
            or not isinstance(pill_count, int)
            or pill_count <= 0
        ):
            raise ValueError("pill_count must be a positive integer")

        command = f"DISPENSE_{box_number}"
        acknowledgement = f"ACK|{command}"
        completion = f"DONE|{command}"
        completed_pills = 0

        for _ in range(pill_count):
            try:
                self.arduino_uno.send_command(command)
            except HardwareControllerError as exc:
                self._raise_dispense_error(
                    box_number,
                    completed_pills,
                    "SEND",
                    exc,
                )

            try:
                self.arduino_uno.wait_for_response(acknowledgement)
            except HardwareControllerError as exc:
                self._raise_dispense_error(
                    box_number,
                    completed_pills,
                    "ACK",
                    exc,
                )

            try:
                self.arduino_uno.wait_for_response(completion)
            except HardwareControllerError as exc:
                self._raise_dispense_error(
                    box_number,
                    completed_pills,
                    "DONE",
                    exc,
                )

            completed_pills += 1

        return {
            "box_number": box_number,
            "requested_pills": pill_count,
            "dispensed_pills": completed_pills,
        }

    @staticmethod
    def _request(
        controller: SerialController,
        command: str,
        expected: str | Sequence[str],
    ) -> str:
        controller.send_command(command)
        return controller.wait_for_response(expected)

    @staticmethod
    def _raise_dispense_error(
        box_number: int,
        completed_pills: int,
        stage: str,
        cause: HardwareControllerError,
    ) -> None:
        raise DispenseError(
            f"DISPENSE_FAILED|BOX={box_number}|COMPLETED={completed_pills}"
            f"|STAGE={stage}|CAUSE={_clean_field(cause)}"
        ) from cause


class MachineReadableArgumentParser(argparse.ArgumentParser):
    """Emit concise structured errors for invalid CLI arguments."""

    def error(self, message: str) -> None:
        self.exit(2, f"ERROR|INVALID_ARGUMENTS|DETAIL={_clean_field(message)}\n")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = MachineReadableArgumentParser(
        description="Control the robot's ESP32 and Arduino UNO.",
    )
    parser.add_argument("--esp32-port", default=ESP32_PORT)
    parser.add_argument("--arduino-port", default=ARDUINO_UNO_PORT)
    parser.add_argument(
        "--esp32-startup-delay",
        type=float,
        default=ESP32_STARTUP_DELAY_SECONDS,
    )
    parser.add_argument(
        "--arduino-startup-delay",
        type=float,
        default=ARDUINO_UNO_STARTUP_DELAY_SECONDS,
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=DEFAULT_READ_TIMEOUT_SECONDS,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ping", help="ping both boards")
    subparsers.add_parser("status", help="read both board statuses")

    dispense_parser = subparsers.add_parser(
        "dispense",
        help="dispense pills sequentially from box 1 or 2",
    )
    dispense_parser.add_argument("box_number", type=int, choices=(1, 2))
    dispense_parser.add_argument("pill_count", type=int)
    return parser


def _build_controller(args: argparse.Namespace) -> RobotHardwareController:
    esp32 = SerialController(
        args.esp32_port,
        ESP32_BAUD_RATE,
        startup_delay=args.esp32_startup_delay,
        read_timeout=args.read_timeout,
    )
    arduino_uno = SerialController(
        args.arduino_port,
        ARDUINO_UNO_BAUD_RATE,
        startup_delay=args.arduino_startup_delay,
        read_timeout=args.read_timeout,
    )
    return RobotHardwareController(esp32=esp32, arduino_uno=arduino_uno)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)

    if args.esp32_startup_delay < 0:
        print(
            "ERROR|INVALID_ARGUMENTS|ESP32_STARTUP_DELAY_MUST_NOT_BE_NEGATIVE",
            file=sys.stderr,
        )
        return 2
    if args.arduino_startup_delay < 0:
        print(
            "ERROR|INVALID_ARGUMENTS|ARDUINO_STARTUP_DELAY_MUST_NOT_BE_NEGATIVE",
            file=sys.stderr,
        )
        return 2
    if args.read_timeout <= 0:
        print("ERROR|INVALID_ARGUMENTS|READ_TIMEOUT_MUST_BE_POSITIVE", file=sys.stderr)
        return 2
    if args.command == "dispense" and args.pill_count <= 0:
        print(
            "ERROR|INVALID_ARGUMENTS|PILL_COUNT_MUST_BE_POSITIVE",
            file=sys.stderr,
        )
        return 2

    controller = _build_controller(args)
    exit_code = 0
    try:
        controller.connect()
        if args.command == "ping":
            for board, response in controller.ping_all().items():
                print(f"{board} -> {response}")
        elif args.command == "status":
            for board, response in controller.get_all_statuses().items():
                print(f"{board} -> {response}")
        else:
            summary = controller.dispense(args.box_number, args.pill_count)
            print(
                f"DISPENSE|BOX={summary['box_number']}"
                f"|REQUESTED={summary['requested_pills']}"
                f"|COMPLETED={summary['dispensed_pills']}"
            )
    except KeyboardInterrupt:
        print("ERROR|INTERRUPTED", file=sys.stderr)
        exit_code = 130
    except HardwareControllerError as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        exit_code = 1
    except ValueError as exc:
        print(f"ERROR|INVALID_VALUE|DETAIL={_clean_field(exc)}", file=sys.stderr)
        exit_code = 1
    finally:
        try:
            controller.close()
        except HardwareControllerError as exc:
            print(f"ERROR|{exc}", file=sys.stderr)
            if exit_code == 0:
                exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
