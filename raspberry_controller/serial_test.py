"""Interactive serial communication tester for an ESP32."""

from __future__ import annotations

import argparse
import sys
from typing import Protocol


BAUD_RATE = 115200
READ_TIMEOUT_SECONDS = 2


class CommandTransport(Protocol):
    """Transport used by the interactive command loop."""

    def send(self, command: str) -> str | None:
        """Send one command and return the ESP32 response, if any."""

    def close(self) -> None:
        """Release transport resources."""


class MockTransport:
    """In-memory ESP32 simulator for testing without hardware."""

    RESPONSES = {
        "PING": "ACK|PING",
        "GET_STATUS": "STATUS|IDLE",
    }

    def send(self, command: str) -> str:
        return self.RESPONSES.get(command, "ERROR|UNKNOWN_COMMAND")

    def close(self) -> None:
        pass


class SerialTransport:
    """pyserial-backed connection to the ESP32."""

    def __init__(self, port: str) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is not installed. Run: pip install -r requirements.txt"
            ) from exc

        try:
            self._connection = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=READ_TIMEOUT_SECONDS,
            )
        except (serial.SerialException, OSError) as exc:
            raise RuntimeError(f"could not open serial port {port}: {exc}") from exc

    def send(self, command: str) -> str | None:
        # The ESP32 protocol requires every command to end with a newline.
        payload = f"{command}\n".encode("utf-8")
        try:
            self._connection.write(payload)
            self._connection.flush()
            response = self._connection.readline()
        except (OSError, self._serial_exception_type()) as exc:
            raise RuntimeError(f"serial communication failed: {exc}") from exc

        if not response:
            return None
        return response.decode("utf-8", errors="replace").rstrip("\r\n")

    def _serial_exception_type(self) -> type[Exception]:
        import serial

        return serial.SerialException

    def close(self) -> None:
        if self._connection.is_open:
            self._connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send interactive newline-terminated commands to an ESP32."
    )
    parser.add_argument(
        "--port",
        help="Serial port, for example COM5 or /dev/ttyUSB0",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="simulate ESP32 responses without hardware",
    )
    args = parser.parse_args()
    if not args.mock and not args.port:
        parser.error("--port is required unless --mock is used")
    return args


def run_interactive(transport: CommandTransport) -> int:
    print("Enter a command (examples: PING, GET_STATUS).")
    print("Press Ctrl+C or Ctrl+D to exit.")

    while True:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nClosing serial tester.")
            return 0

        if not command:
            continue

        try:
            response = transport.send(command)
        except RuntimeError as exc:
            print(f"Connection error: {exc}", file=sys.stderr)
            return 1

        if response is None:
            print("ESP32 response: <no response before timeout>")
        else:
            print(f"ESP32 response: {response}")


def main() -> int:
    args = parse_args()

    try:
        if args.mock:
            transport: CommandTransport = MockTransport()
            print(f"Mock mode enabled (baud rate: {BAUD_RATE}).")
        else:
            transport = SerialTransport(args.port)
            print(f"Connected to {args.port} at {BAUD_RATE} baud.")
    except RuntimeError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        return 1

    try:
        return run_interactive(transport)
    finally:
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
