"""Unified serial controller for the robot's ESP32 and Arduino UNO."""

from __future__ import annotations

import argparse
import errno
import os
import queue
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterator, Sequence


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
MAX_SERIAL_LINE_BYTES = 4096


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
        self._response_queue: queue.Queue[str] = queue.Queue()
        self._event_queue: queue.Queue[str] = queue.Queue()
        self._reader_stop = threading.Event()
        self._reader_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._reader_error: SerialConnectionError | None = None
        self._response_state_lock = threading.Lock()
        self._active_response_queue: queue.Queue[str] | None = None

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
            self._reset_dispatcher()
            self._ensure_reader_started()
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

        self._reader_stop.set()
        try:
            connection.close()
        except self._communication_exceptions() as exc:
            raise SerialConnectionError(
                f"SERIAL_CLOSE_FAILED|PORT={_clean_field(self.port)}"
                f"|DETAIL={_clean_field(exc)}"
            ) from exc
        finally:
            reader_thread = self._reader_thread
            if (
                reader_thread is not None
                and reader_thread is not threading.current_thread()
            ):
                reader_thread.join(timeout=SERIAL_POLL_TIMEOUT_SECONDS * 2)
            self._reader_thread = None

    def send_command(self, command: str) -> None:
        """Send one ASCII command terminated by a newline."""

        connection = self._require_connection()
        self._ensure_reader_started()
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

    def wait_for_response(
        self,
        expected: str | Sequence[str],
        *,
        validator: Callable[[str], bool] | None = None,
        response_prefix: str | None = None,
        overall_timeout: float | None = None,
    ) -> str:
        """Scan serial lines until an expected response or overall timeout."""

        self._require_connection()
        expected_responses = (
            (expected,) if isinstance(expected, str) else tuple(expected)
        )
        if not expected_responses:
            raise ValueError("at least one expected response is required")

        expected_text = ",".join(expected_responses)
        timeout = self.read_timeout if overall_timeout is None else overall_timeout
        if timeout <= 0:
            raise ValueError("overall_timeout must be positive")
        deadline = time.monotonic() + timeout
        last_non_empty_response: str | None = None
        with self._response_state_lock:
            response_queue = self._active_response_queue or self._response_queue

        while True:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                break

            # Keep each read short so asynchronous lines cannot extend the deadline.
            try:
                response = response_queue.get(
                    timeout=min(SERIAL_POLL_TIMEOUT_SECONDS, remaining_time)
                )
            except queue.Empty:
                if self._reader_error is not None:
                    raise self._reader_error
                continue

            last_non_empty_response = response
            if response.startswith("ERROR|"):
                raise UnexpectedSerialResponse(
                    f"UNEXPECTED_RESPONSE|PORT={_clean_field(self.port)}"
                    f"|EXPECTED={_clean_field(expected_text)}"
                    f"|RECEIVED={_clean_field(response)}"
                )
            if response in expected_responses or (
                validator is not None and validator(response)
            ):
                return response
            if response_prefix is not None and response.startswith(response_prefix):
                raise UnexpectedSerialResponse(
                    f"UNEXPECTED_RESPONSE|PORT={_clean_field(self.port)}"
                    f"|EXPECTED={_clean_field(expected_text)}"
                    f"|RECEIVED={_clean_field(response)}"
                )

        timeout_message = (
            f"SERIAL_TIMEOUT|PORT={_clean_field(self.port)}"
            f"|EXPECTED={_clean_field(expected_text)}"
        )
        if last_non_empty_response is not None:
            timeout_message += (
                f"|LAST_RECEIVED={_clean_field(last_non_empty_response)}"
            )
        raise SerialResponseTimeout(timeout_message)

    @contextmanager
    def response_transaction(self) -> Iterator[None]:
        """Register the command response destination before command bytes are sent."""

        transaction_queue: queue.Queue[str] = queue.Queue()
        with self._response_state_lock:
            if self._active_response_queue is not None:
                raise RuntimeError("A serial response transaction is already active")
            self._active_response_queue = transaction_queue
        try:
            yield
        finally:
            with self._response_state_lock:
                if self._active_response_queue is transaction_queue:
                    self._active_response_queue = None

    def get_async_line(self, timeout: float = 0.0) -> str | None:
        """Return one line dispatched by the sole serial reader as telemetry."""

        if timeout < 0:
            raise ValueError("timeout must not be negative")
        self._require_connection()
        self._ensure_reader_started()
        try:
            return self._event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def reader_running(self) -> bool:
        thread = self._reader_thread
        return bool(thread is not None and thread.is_alive())

    def _ensure_reader_started(self) -> None:
        with self._reader_lock:
            if self._reader_thread is not None and self._reader_thread.is_alive():
                return
            connection = self._require_connection()
            self._reader_stop.clear()
            self._reader_error = None
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                args=(connection,),
                name=f"serial-reader-{self.port}",
                daemon=True,
            )
            self._reader_thread.start()

    def _reader_loop(self, connection: Any) -> None:
        pending_bytes = bytearray()
        while not self._reader_stop.is_set():
            connection.timeout = min(
                SERIAL_POLL_TIMEOUT_SECONDS,
                self.read_timeout,
            )
            try:
                raw_line = connection.readline()
            except self._communication_exceptions() as exc:
                if not self._reader_stop.is_set():
                    self._reader_error = SerialConnectionError(
                        f"SERIAL_READ_FAILED|PORT={_clean_field(self.port)}"
                        f"|DETAIL={_clean_field(exc)}"
                    )
                return

            if not raw_line:
                self._reader_stop.wait(0.001)
                continue

            pending_bytes.extend(raw_line)
            while b"\n" in pending_bytes:
                raw_complete_line, _, remainder = pending_bytes.partition(b"\n")
                pending_bytes = bytearray(remainder)
                line = raw_complete_line.decode(
                    "ascii",
                    errors="replace",
                ).rstrip("\r")
                if line:
                    self._dispatch_complete_line(line)

            if len(pending_bytes) > MAX_SERIAL_LINE_BYTES:
                self._reader_error = SerialConnectionError(
                    f"SERIAL_LINE_TOO_LONG|PORT={_clean_field(self.port)}"
                )
                return

    def _dispatch_complete_line(self, line: str) -> None:
        if self._is_async_line(line):
            self._event_queue.put(line)
            return

        with self._response_state_lock:
            response_queue = self._active_response_queue or self._response_queue
        response_queue.put(line)

    @staticmethod
    def _is_async_line(line: str) -> bool:
        if line.startswith("EVENT|") or line.startswith("LINE|RECOVERY|"):
            return True

        response_prefixes = (
            "ACK|",
            "DONE|",
            "ERROR|",
            "STATUS|",
            "RTC|",
            "HAND|",
            "LINE|",
            "LINE_STATUS|",
        )
        return not line.startswith(response_prefixes)

    def _reset_dispatcher(self) -> None:
        self._reader_stop.set()
        self._reader_thread = None
        with self._response_state_lock:
            self._response_queue = queue.Queue()
            self._active_response_queue = None
        self._event_queue = queue.Queue()
        self._reader_error = None

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
    ESP32_STATUS_RESPONSES = (
        "STATUS|IDLE",
        "STATUS|MANUAL",
        "STATUS|AUTONOMOUS",
        "STATUS|LINE_FOLLOWING",
        "STATUS|INTERSECTION",
        "STATUS|LINE_LOST",
        "STATUS|NAVIGATION",
        "STATUS|NAVIGATION_FAILED",
    )
    HAND_STATUS_RESPONSES = ("HAND|DETECTED", "HAND|WAITING")
    MEDICINE_LCD_STATES = {
        "HAND_WAITING",
        "HAND_DETECTED",
        "DISPENSING",
        "MEDICINE_READY",
        "NO_HAND",
        "DISPENSE_FAILED",
    }
    LINE_FOLLOW_STATES = {
        "IDLE",
        "ACQUIRING",
        "CENTERED",
        "CORRECTING_LEFT",
        "CORRECTING_RIGHT",
        "SEARCHING_LEFT",
        "SEARCHING_RIGHT",
        "INTERSECTION",
        "LINE_LOST",
        "NAVIGATION_FAILED",
    }
    NAVIGATION_STATES = {
        "GOING_STRAIGHT",
        "CENTERING_LEFT",
        "CENTERING_RIGHT",
        "PIVOTING_LEFT",
        "PIVOTING_RIGHT",
        "PIVOTING_SEARCH_LEFT",
        "PIVOTING_SEARCH_RIGHT",
        "ALIGNING_LEFT",
        "ALIGNING_RIGHT",
        "PIVOT_SEARCH_LEFT",
        "PIVOT_SEARCH_RIGHT",
        "SENSOR_ALIGN_LEFT",
        "SENSOR_ALIGN_RIGHT",
        "LOCKING_LINE_LEFT",
        "LOCKING_LINE_RIGHT",
        "REACQUIRING_LEFT",
        "REACQUIRING_RIGHT",
        "TURNING_LEFT",
        "TURNING_RIGHT",
        "ACQUIRING_LEFT",
        "ACQUIRING_RIGHT",
        "ACQUIRING_STRAIGHT",
        "UTURN_PIVOT_SEARCH",
        "UTURN_SENSOR_ALIGN",
        "UTURN_LINE_LOCK",
    }
    WATER_MIN_DURATION_MS = 100
    WATER_MAX_DURATION_MS = 60000
    DISK_SLOT_COUNT = 8

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
        self._esp32_transaction_lock = threading.RLock()
        self._arduino_transaction_lock = threading.RLock()

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
                self.ESP32_STATUS_RESPONSES,
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

    def manual_forward(self) -> str:
        """Start persistent non-blocking manual forward drive."""

        return self._request(
            self.esp32, "MANUAL_FORWARD", "ACK|MANUAL_FORWARD"
        )

    def manual_backward(self) -> str:
        """Start persistent non-blocking manual backward drive."""

        return self._request(
            self.esp32, "MANUAL_BACKWARD", "ACK|MANUAL_BACKWARD"
        )

    def manual_left(self) -> str:
        """Start a persistent non-blocking manual left pivot."""

        return self._request(self.esp32, "MANUAL_LEFT", "ACK|MANUAL_LEFT")

    def manual_right(self) -> str:
        """Start a persistent non-blocking manual right pivot."""

        return self._request(self.esp32, "MANUAL_RIGHT", "ACK|MANUAL_RIGHT")

    def manual_forward_left(self) -> str:
        """Start a persistent forward-left manual arc."""

        return self._request(
            self.esp32,
            "MANUAL_FORWARD_LEFT",
            "ACK|MANUAL_FORWARD_LEFT",
        )

    def manual_forward_right(self) -> str:
        """Start a persistent forward-right manual arc."""

        return self._request(
            self.esp32,
            "MANUAL_FORWARD_RIGHT",
            "ACK|MANUAL_FORWARD_RIGHT",
        )

    def manual_backward_left(self) -> str:
        """Start a persistent backward-left manual arc."""

        return self._request(
            self.esp32,
            "MANUAL_BACKWARD_LEFT",
            "ACK|MANUAL_BACKWARD_LEFT",
        )

    def manual_backward_right(self) -> str:
        """Start a persistent backward-right manual arc."""

        return self._request(
            self.esp32,
            "MANUAL_BACKWARD_RIGHT",
            "ACK|MANUAL_BACKWARD_RIGHT",
        )

    def manual_stop(self) -> str:
        """Stop manual drive motors without using a blocking maneuver."""

        return self._request(self.esp32, "MANUAL_STOP", "ACK|MANUAL_STOP")

    def get_line_reading(self) -> str:
        """Return one validated active-low sensor reading from the ESP32."""

        return self._request(
            self.esp32,
            "GET_LINE",
            "VALID_LINE_READING",
            validator=self._is_valid_line_reading,
            response_prefix="LINE|",
        )

    def get_line_status(self) -> str:
        """Return the validated line-follow mode, state, and latest pattern."""

        return self._request(
            self.esp32,
            "GET_LINE_STATUS",
            "VALID_LINE_STATUS",
            validator=self._is_valid_line_status,
            response_prefix="LINE_STATUS|",
        )

    def start_line_follow(self) -> str:
        """Start non-blocking line following on the ESP32."""

        return self._request(
            self.esp32,
            "START_LINE_FOLLOW",
            "ACK|LINE_FOLLOW_STARTED",
        )

    def stop_line_follow(self) -> str:
        """Stop line following and the drive motors on the ESP32."""

        return self._request(
            self.esp32,
            "STOP_LINE_FOLLOW",
            "ACK|LINE_FOLLOW_STOPPED",
        )

    def intersection_left(self) -> str:
        """Start non-blocking acquisition of the left intersection branch."""

        return self._request(
            self.esp32,
            "INTERSECTION_LEFT",
            "ACK|INTERSECTION_LEFT_STARTED",
            response_prefix="ACK|INTERSECTION_",
        )

    def intersection_right(self) -> str:
        """Start non-blocking acquisition of the right intersection branch."""

        return self._request(
            self.esp32,
            "INTERSECTION_RIGHT",
            "ACK|INTERSECTION_RIGHT_STARTED",
            response_prefix="ACK|INTERSECTION_",
        )

    def intersection_straight(self) -> str:
        """Start non-blocking acquisition of the straight intersection branch."""

        return self._request(
            self.esp32,
            "INTERSECTION_STRAIGHT",
            "ACK|INTERSECTION_STRAIGHT_STARTED",
            response_prefix="ACK|INTERSECTION_",
        )

    def u_turn(self) -> str:
        """Start the ESP32's bounded, sensor-guided physical U-turn."""

        return self._request(
            self.esp32,
            "U_TURN",
            "ACK|U_TURN_STARTED",
            response_prefix="ACK|U_TURN",
        )

    def get_esp32_event(self, timeout: float = 0.0) -> str | None:
        """Consume ESP32 telemetry without reading the serial connection directly."""

        return self.esp32.get_async_line(timeout)

    def get_hand_status(self) -> str:
        """Read the ESP32's existing debounced hand sensor state."""

        return self._request(
            self.esp32,
            "GET_HAND",
            self.HAND_STATUS_RESPONSES,
            response_prefix="HAND|",
        )

    def wait_for_hand(self, timeout_seconds: float) -> bool:
        """Poll the ESP32 hand state until confirmed or the bounded timeout."""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        deadline = time.monotonic() + timeout_seconds
        while True:
            if self.get_hand_status() == "HAND|DETECTED":
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def show_medicine_workflow_status(self, state: str) -> str:
        """Use the ESP32's single LCD implementation for patient prompts."""

        if state not in self.MEDICINE_LCD_STATES:
            raise ValueError(f"unsupported medicine LCD state: {state!r}")
        acknowledgement = f"ACK|LCD|STATE={state}"
        return self._request(
            self.esp32,
            f"LCD|STATE={state}",
            acknowledgement,
            response_prefix="ACK|LCD|STATE=",
        )

    def get_rtc_datetime(self) -> datetime:
        """Read and strictly parse the DS1302 wall-clock response."""

        response = self._request(
            self.esp32,
            "GET_RTC",
            "VALID_RTC_RESPONSE",
            validator=self._is_valid_rtc_response,
            response_prefix="RTC|",
        )
        return self.parse_rtc_response(response)

    def dispense_water(self, duration_ms: int) -> dict[str, int]:
        """Run the ESP32 pump for one bounded, acknowledged duration."""

        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, int)
            or duration_ms < self.WATER_MIN_DURATION_MS
            or duration_ms > self.WATER_MAX_DURATION_MS
        ):
            raise ValueError(
                "duration_ms must be between "
                f"{self.WATER_MIN_DURATION_MS} and {self.WATER_MAX_DURATION_MS}"
            )

        command = f"WATER_DISPENSE|MS={duration_ms}"
        acknowledgement = f"ACK|WATER|DURATION_MS={duration_ms}"
        completion = f"DONE|WATER|DURATION_MS={duration_ms}"
        with self._esp32_transaction_lock:
            with self.esp32.response_transaction():
                self.esp32.send_command(command)
                self.esp32.wait_for_response(
                    acknowledgement,
                    response_prefix="ACK|WATER|",
                )
                self.esp32.wait_for_response(
                    completion,
                    response_prefix="DONE|WATER|",
                    overall_timeout=(
                        (duration_ms / 1000) + self.esp32.read_timeout
                    ),
                )

        return {"duration_ms": duration_ms}

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

        with self._arduino_transaction_lock:
            for _ in range(pill_count):
                with self.arduino_uno.response_transaction():
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
                            self._dispense_sensor_error_code(exc, command)
                            or exc,
                        )

                completed_pills += 1

        return {
            "box_number": box_number,
            "requested_pills": pill_count,
            "dispensed_pills": completed_pills,
        }

    def get_disk_status(self) -> dict[str, dict[str, bool | int]]:
        """Read both volatile UNO disk-calibration states on its owned link."""

        response = self._request(
            self.arduino_uno,
            "GET_DISK_STATUS",
            "VALID_DISK_STATUS",
            validator=self._is_valid_disk_status,
            response_prefix="DISK_STATUS|",
        )
        return self.parse_disk_status(response)

    def set_slot_zero(self, box_number: int) -> dict[str, bool | int]:
        """Record a manually aligned slot zero without moving either motor."""

        if isinstance(box_number, bool) or box_number not in (1, 2):
            raise ValueError("box_number must be 1 or 2")

        command = f"SET_SLOT_ZERO_{box_number}"
        acknowledgement = f"ACK|{command}"
        self._request(self.arduino_uno, command, acknowledgement)
        return self.get_disk_status()[f"disk{box_number}"]

    def _request(
        self,
        controller: SerialController,
        command: str,
        expected: str | Sequence[str],
        *,
        validator: Callable[[str], bool] | None = None,
        response_prefix: str | None = None,
    ) -> str:
        transaction_lock = (
            self._esp32_transaction_lock
            if controller is self.esp32
            else self._arduino_transaction_lock
        )
        with transaction_lock:
            with controller.response_transaction():
                controller.send_command(command)
                if validator is None and response_prefix is None:
                    return controller.wait_for_response(expected)
                return controller.wait_for_response(
                    expected,
                    validator=validator,
                    response_prefix=response_prefix,
                )

    @staticmethod
    def _is_valid_line_reading(response: str) -> bool:
        parts = response.split("|")
        if len(parts) != 7 or parts[0] != "LINE":
            return False

        sensor_values: list[str] = []
        for index, part in enumerate(parts[1:6], start=1):
            expected_prefix = f"O{index}="
            if not part.startswith(expected_prefix):
                return False
            value = part[len(expected_prefix) :]
            if value not in ("0", "1"):
                return False
            sensor_values.append(value)

        pattern_part = parts[6]
        return pattern_part == f"PATTERN={''.join(sensor_values)}"

    @staticmethod
    def parse_rtc_response(response: str) -> datetime:
        """Parse the exact ESP32 GET_RTC contract or raise ValueError."""

        parts = response.split("|")
        expected_keys = ("YYYY", "MM", "DD", "HH", "MIN", "SEC")
        expected_widths = (4, 2, 2, 2, 2, 2)
        if len(parts) != 7 or parts[0] != "RTC":
            raise ValueError("invalid RTC response structure")

        values: list[int] = []
        for part, key, width in zip(parts[1:], expected_keys, expected_widths):
            prefix = f"{key}="
            raw_value = part.removeprefix(prefix)
            if (
                not part.startswith(prefix)
                or len(raw_value) != width
                or not raw_value.isascii()
                or not raw_value.isdigit()
            ):
                raise ValueError(f"invalid RTC field {key}")
            values.append(int(raw_value))

        try:
            return datetime(*values)
        except ValueError as exc:
            raise ValueError("invalid RTC date or time") from exc

    @classmethod
    def _is_valid_rtc_response(cls, response: str) -> bool:
        try:
            cls.parse_rtc_response(response)
        except ValueError:
            return False
        return True

    @classmethod
    def _is_valid_line_status(cls, response: str) -> bool:
        parts = response.split("|")
        if len(parts) != 4 or parts[0] != "LINE_STATUS":
            return False

        mode = parts[1].removeprefix("MODE=")
        state = parts[2].removeprefix("STATE=")
        pattern = parts[3].removeprefix("PATTERN=")
        return (
            parts[1].startswith("MODE=")
            and mode in ("FOLLOWING", "STOPPED", "NAVIGATION")
            and parts[2].startswith("STATE=")
            and (
                (mode == "NAVIGATION" and state in cls.NAVIGATION_STATES)
                or (mode != "NAVIGATION" and state in cls.LINE_FOLLOW_STATES)
            )
            and parts[3].startswith("PATTERN=")
            and len(pattern) == 5
            and all(value in "01" for value in pattern)
        )

    @staticmethod
    def _dispense_sensor_error_code(
        cause: HardwareControllerError,
        command: str,
    ) -> str | None:
        """Extract UNO sensor failures from an immediate ERROR response."""

        response_prefix = f"RECEIVED=ERROR|{command}|CODE="
        message = str(cause)
        start = message.find(response_prefix)
        if start < 0:
            return None
        code = message[start + len(response_prefix) :].split("|", 1)[0]
        return (
            code
            if code in {"PILL_TIMEOUT", "SENSOR_STUCK", "DISK_NOT_CALIBRATED"}
            else None
        )

    @classmethod
    def _is_valid_disk_status(cls, response: str) -> bool:
        try:
            cls.parse_disk_status(response)
        except ValueError:
            return False
        return True

    @classmethod
    def parse_disk_status(cls, response: str) -> dict[str, dict[str, bool | int]]:
        """Strictly parse the UNO's machine-readable disk status response."""

        fields = response.split("|")
        if len(fields) != 5 or fields[0] != "DISK_STATUS":
            raise ValueError("invalid disk status response")
        expected = {
            "DISK1_CALIBRATED",
            "DISK1_SLOT",
            "DISK2_CALIBRATED",
            "DISK2_SLOT",
        }
        values: dict[str, str] = {}
        for field in fields[1:]:
            if "=" not in field:
                raise ValueError("invalid disk status field")
            key, value = field.split("=", 1)
            if key not in expected or key in values:
                raise ValueError("invalid disk status field")
            values[key] = value
        if set(values) != expected:
            raise ValueError("incomplete disk status response")

        def calibrated(key: str) -> bool:
            if values[key] not in {"0", "1"}:
                raise ValueError("invalid calibration flag")
            return values[key] == "1"

        def slot(key: str) -> int:
            try:
                value = int(values[key])
            except ValueError as exc:
                raise ValueError("invalid disk slot") from exc
            if value < 0 or value >= cls.DISK_SLOT_COUNT:
                raise ValueError("invalid disk slot")
            return value

        return {
            "disk1": {
                "calibrated": calibrated("DISK1_CALIBRATED"),
                "slot": slot("DISK1_SLOT"),
            },
            "disk2": {
                "calibrated": calibrated("DISK2_CALIBRATED"),
                "slot": slot("DISK2_SLOT"),
            },
        }

    @staticmethod
    def _raise_dispense_error(
        box_number: int,
        completed_pills: int,
        stage: str,
        cause: HardwareControllerError | str,
    ) -> None:
        error = DispenseError(
            f"DISPENSE_FAILED|BOX={box_number}|COMPLETED={completed_pills}"
            f"|STAGE={stage}|CAUSE={_clean_field(cause)}"
        )
        if isinstance(cause, BaseException):
            raise error from cause
        raise error


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
