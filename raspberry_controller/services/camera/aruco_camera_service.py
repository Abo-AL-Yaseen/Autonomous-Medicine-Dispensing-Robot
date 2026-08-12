"""Read-only USB camera service for confirmed ArUco marker diagnostics."""

from __future__ import annotations

import importlib
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass
from typing import Any


ARUCO_DICTIONARY_NAME = "DICT_4X4_50"
DEFAULT_CAMERA_DEVICE = "/dev/video0"
DEFAULT_CAMERA_WIDTH = 640
DEFAULT_CAMERA_HEIGHT = 480
DEFAULT_CONFIRM_FRAMES = 3
DEFAULT_MIN_MARKER_AREA = 2500.0
DEFAULT_MIN_AREA_RATIO = 1.4
DEFAULT_PREVIEW_FPS = 12.0
DEFAULT_FRAME_WAIT_SECONDS = 1.0
FRAME_HISTORY_MINIMUM = 8

# Diagnostic-only local mapping. Laravel remains the authoritative map and a
# later integration phase can replace this lookup without changing detection.
APPROVED_MARKERS: dict[int, tuple[str, str]] = {
    0: ("NODE_0", "intersection"),
    1: ("NODE_1", "intersection"),
    2: ("NODE_2", "intersection"),
    11: ("ROOM_1", "room"),
    12: ("ROOM_2", "room"),
    13: ("ROOM_3", "room"),
    14: ("ROOM_4", "room"),
    15: ("ROOM_5", "room"),
}

CaptureFactory = Callable[[Any, str], Any]


@dataclass(frozen=True)
class CameraSettings:
    """Camera and marker-confirmation settings loaded at application startup."""

    enabled: bool = True
    device: str = DEFAULT_CAMERA_DEVICE
    width: int = DEFAULT_CAMERA_WIDTH
    height: int = DEFAULT_CAMERA_HEIGHT
    confirm_frames: int = DEFAULT_CONFIRM_FRAMES
    min_marker_area: float = DEFAULT_MIN_MARKER_AREA
    min_area_ratio: float = DEFAULT_MIN_AREA_RATIO

    @classmethod
    def from_environment(cls) -> "CameraSettings":
        return cls(
            enabled=_read_bool_setting("CAMERA_ENABLED", True),
            device=os.getenv("CAMERA_DEVICE", DEFAULT_CAMERA_DEVICE),
            width=_read_positive_int_setting("CAMERA_WIDTH", DEFAULT_CAMERA_WIDTH),
            height=_read_positive_int_setting("CAMERA_HEIGHT", DEFAULT_CAMERA_HEIGHT),
            confirm_frames=_read_positive_int_setting(
                "ARUCO_CONFIRM_FRAMES",
                DEFAULT_CONFIRM_FRAMES,
            ),
            min_marker_area=_read_positive_float_setting(
                "ARUCO_MIN_MARKER_AREA",
                DEFAULT_MIN_MARKER_AREA,
            ),
            min_area_ratio=_read_min_area_ratio_setting(
                "ARUCO_MIN_AREA_RATIO",
                DEFAULT_MIN_AREA_RATIO,
            ),
        )


@dataclass(frozen=True)
class MarkerDetectionResult:
    camera_available: bool
    detected: bool
    confirmed: bool
    marker_id: int | None = None
    node_name: str | None = None
    marker_type: str | None = None
    area: int | None = None
    consecutive_frames: int = 0
    second_marker_id: int | None = None
    second_area: int | None = None
    area_ratio: float | None = None
    ambiguous: bool = False
    expected_marker_id: int | None = None
    selection_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ArucoCameraService:
    """Own one camera resource and detect approved, sufficiently large markers.

    This class deliberately has no hardware-controller or serial dependency.
    Detection never dispatches movement or navigation commands.
    """

    def __init__(
        self,
        settings: CameraSettings,
        *,
        cv2_module: Any | None = None,
        capture_factory: CaptureFactory | None = None,
    ) -> None:
        self.settings = settings
        self._cv2 = cv2_module
        self._capture_factory = capture_factory
        self._capture: Any | None = None
        self._dictionary: Any | None = None
        self._parameters: Any | None = None
        self._detector: Any | None = None
        self._candidate_id: int | None = None
        self._candidate_frames = 0
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._detection_lock = threading.Lock()
        self._confirmation_lock = threading.RLock()
        self._detector_lock = threading.Lock()
        self._frame_condition = threading.Condition()
        self._latest_frame: Any | None = None
        self._frame_sequence = 0
        self._frame_history: deque[tuple[int, Any]] = deque(
            maxlen=max(FRAME_HISTORY_MINIMUM, settings.confirm_frames * 2)
        )
        self._last_detection_sequence: int | None = None
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def start(self) -> bool:
        """Open and configure the camera without propagating availability failures."""

        with self._lock:
            if not self.settings.enabled:
                self._last_error = None
                return False

            if self._camera_is_open():
                if not self._reader_is_running():
                    self._reset_frame_buffer()
                    self._start_reader()
                return True

            try:
                cv2_module = self._cv2 or importlib.import_module("cv2")
                self._cv2 = cv2_module
                aruco = cv2_module.aruco
                dictionary_id = getattr(aruco, ARUCO_DICTIONARY_NAME)
                self._dictionary = aruco.getPredefinedDictionary(dictionary_id)
                self._parameters = (
                    aruco.DetectorParameters()
                    if hasattr(aruco, "DetectorParameters")
                    else aruco.DetectorParameters_create()
                )
                self._detector = (
                    aruco.ArucoDetector(self._dictionary, self._parameters)
                    if hasattr(aruco, "ArucoDetector")
                    else None
                )

                if self._capture_factory is None:
                    self._capture = cv2_module.VideoCapture(
                        self.settings.device,
                        cv2_module.CAP_V4L2,
                    )
                else:
                    self._capture = self._capture_factory(
                        cv2_module,
                        self.settings.device,
                    )

                if not self._camera_is_open():
                    self._release_capture()
                    self._last_error = "CAMERA_UNAVAILABLE"
                    return False

                self._set_capture_dimensions()
                self._reset_frame_buffer()
                self._start_reader()
                self._last_error = None
                return True
            except Exception:
                self._release_capture()
                self._last_error = "CAMERA_INITIALIZATION_FAILED"
                return False

    def close(self) -> None:
        """Release the camera cleanly and reset confirmation state."""

        self._reader_stop.set()
        with self._frame_condition:
            self._frame_condition.notify_all()
        reader_thread = self._reader_thread
        if (
            reader_thread is not None
            and reader_thread is not threading.current_thread()
        ):
            reader_thread.join(timeout=1.0)
        with self._lock:
            self._release_capture()
            self._reset_confirmation()
            self._reader_thread = None
        if reader_thread is not None and reader_thread.is_alive():
            reader_thread.join(timeout=0.5)
        self._reset_frame_buffer()

    def status(self) -> dict[str, object]:
        with self._lock:
            camera_open = self._camera_is_open()
            reader_running = self._reader_is_running()
            return {
                "enabled": self.settings.enabled,
                "device": self.settings.device,
                "camera_open": camera_open,
                "camera_available": camera_open and reader_running,
                "dictionary": ARUCO_DICTIONARY_NAME,
                "width": self.settings.width,
                "height": self.settings.height,
                "confirm_frames": self.settings.confirm_frames,
                "min_marker_area": self.settings.min_marker_area,
                "min_area_ratio": self.settings.min_area_ratio,
                "error": self._last_error,
            }

    def detect(
        self,
        *,
        expected_marker_id: int | None = None,
        after_sequence: int | None = None,
    ) -> MarkerDetectionResult:
        """Inspect consecutive frames supplied by the sole camera reader.

        A supplied ``after_sequence`` requires every confirmation frame to be
        strictly newer than that frame, without pausing capture or streaming.
        """

        with self._detection_lock:
            if not self._camera_is_available():
                return MarkerDetectionResult(
                    camera_available=False,
                    detected=False,
                    confirmed=False,
                )

            if after_sequence is not None:
                # A candidate from before the physical event cannot count
                # toward that event's navigation decision.
                self._reset_confirmation()
            detection_after_sequence = _later_sequence(
                self._last_detection_sequence,
                after_sequence,
            )
            result = MarkerDetectionResult(
                camera_available=True,
                detected=False,
                confirmed=False,
            )
            for _ in range(self.settings.confirm_frames):
                try:
                    next_frame = self._next_detection_frame(
                        detection_after_sequence,
                        timeout=DEFAULT_FRAME_WAIT_SECONDS,
                    )
                    if next_frame is None:
                        raise RuntimeError("camera frame unavailable")
                    sequence, frame = next_frame
                    self._last_detection_sequence = sequence
                    detection_after_sequence = sequence
                    result = self._detect_frame(
                        frame,
                        expected_marker_id=expected_marker_id,
                    )
                except Exception:
                    self._set_last_error("CAMERA_READ_FAILED")
                    self._reset_confirmation()
                    return MarkerDetectionResult(
                        camera_available=self._camera_is_available(),
                        detected=False,
                        confirmed=False,
                    )
                if result.confirmed:
                    break

            return result

    def current_frame_sequence(self) -> int:
        """Return the newest captured frame sequence without consuming it."""

        with self._frame_condition:
            return self._frame_sequence

    def process_detections(
        self,
        marker_ids: Any,
        corners: Sequence[Any],
        *,
        camera_available: bool = True,
        expected_marker_id: int | None = None,
    ) -> MarkerDetectionResult:
        """Filter one detector result and update consecutive-frame state."""

        with self._confirmation_lock:
            return self._process_detections_locked(
                marker_ids,
                corners,
                camera_available=camera_available,
                expected_marker_id=expected_marker_id,
            )

    def _process_detections_locked(
        self,
        marker_ids: Any,
        corners: Sequence[Any],
        *,
        camera_available: bool,
        expected_marker_id: int | None,
    ) -> MarkerDetectionResult:
        observations_by_marker: dict[int, int] = {}
        flattened_ids = _flatten_marker_ids(marker_ids)

        for marker_id, marker_corners in zip(flattened_ids, corners, strict=False):
            if marker_id not in APPROVED_MARKERS:
                continue

            area = _polygon_area(marker_corners)
            if area < self.settings.min_marker_area:
                continue

            rounded_area = int(round(area))
            observations_by_marker[marker_id] = max(
                rounded_area,
                observations_by_marker.get(marker_id, 0),
            )

        if not observations_by_marker:
            self._reset_confirmation()
            return MarkerDetectionResult(
                camera_available=camera_available,
                detected=False,
                confirmed=False,
                expected_marker_id=expected_marker_id,
                selection_error="NO_VALID_MARKER",
            )

        observations = sorted(
            observations_by_marker.items(),
            key=lambda item: (-item[1], item[0]),
        )
        marker_id, area = observations[0]
        second_marker_id: int | None = None
        second_area: int | None = None
        area_ratio: float | None = None
        if len(observations) > 1:
            second_marker_id, second_area = observations[1]
            area_ratio = area / second_area if second_area > 0 else None

        ambiguous = bool(
            area_ratio is not None
            and area_ratio < self.settings.min_area_ratio
        )
        unexpected = bool(
            expected_marker_id is not None
            and marker_id != expected_marker_id
        )
        node_name, marker_type = APPROVED_MARKERS[marker_id]

        if ambiguous or unexpected:
            self._reset_confirmation()
            return MarkerDetectionResult(
                camera_available=camera_available,
                detected=True,
                confirmed=False,
                marker_id=marker_id,
                node_name=node_name,
                marker_type=marker_type,
                area=area,
                consecutive_frames=0,
                second_marker_id=second_marker_id,
                second_area=second_area,
                area_ratio=area_ratio,
                ambiguous=ambiguous,
                expected_marker_id=expected_marker_id,
                selection_error=(
                    "AMBIGUOUS_MARKERS" if ambiguous else "UNEXPECTED_MARKER"
                ),
            )

        if marker_id == self._candidate_id:
            self._candidate_frames += 1
        else:
            self._candidate_id = marker_id
            self._candidate_frames = 1

        return MarkerDetectionResult(
            camera_available=camera_available,
            detected=True,
            confirmed=self._candidate_frames >= self.settings.confirm_frames,
            marker_id=marker_id,
            node_name=node_name,
            marker_type=marker_type,
            area=area,
            consecutive_frames=self._candidate_frames,
            second_marker_id=second_marker_id,
            second_area=second_area,
            area_ratio=area_ratio,
            ambiguous=False,
            expected_marker_id=expected_marker_id,
        )

    def _detect_frame(
        self,
        frame: Any,
        *,
        expected_marker_id: int | None,
    ) -> MarkerDetectionResult:
        corners, marker_ids = self._detect_markers(frame)
        return self.process_detections(
            marker_ids,
            corners,
            expected_marker_id=expected_marker_id,
        )

    def get_preview_jpeg(
        self,
        *,
        after_sequence: int | None = None,
        timeout: float = DEFAULT_FRAME_WAIT_SECONDS,
    ) -> tuple[int, bytes] | None:
        """Encode one annotated copy of a buffered frame for browser preview."""

        frame_item = self._latest_frame_copy(after_sequence, timeout)
        if frame_item is None or not self._camera_is_available():
            return None

        sequence, frame = frame_item
        try:
            preview = self._draw_preview_overlay(frame)
            encode_options = []
            if hasattr(self._cv2, "IMWRITE_JPEG_QUALITY"):
                encode_options = [self._cv2.IMWRITE_JPEG_QUALITY, 75]
            encoded_ok, encoded = self._cv2.imencode(
                ".jpg",
                preview,
                encode_options,
            )
            if not encoded_ok:
                raise RuntimeError("JPEG encoding failed")
            return sequence, encoded.tobytes()
        except Exception:
            self._set_last_error("CAMERA_PREVIEW_ENCODING_FAILED")
            return None

    def mjpeg_stream(
        self,
        first_frame: tuple[int, bytes],
        *,
        fps: float = DEFAULT_PREVIEW_FPS,
    ) -> Iterator[bytes]:
        """Yield independently paced MJPEG parts without blocking camera reads."""

        if fps <= 0:
            raise ValueError("fps must be positive")

        sequence, jpeg = first_frame
        interval = 1.0 / fps
        while not self._reader_stop.is_set():
            yield _mjpeg_part(jpeg)
            if self._reader_stop.wait(interval):
                return
            next_frame = self.get_preview_jpeg(
                after_sequence=sequence,
                timeout=DEFAULT_FRAME_WAIT_SECONDS,
            )
            if next_frame is None:
                if not self._camera_is_available():
                    return
                continue
            sequence, jpeg = next_frame

    def _start_reader(self) -> None:
        if self._reader_is_running():
            return
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(
            target=self._camera_reader_loop,
            name="aruco-camera-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def _camera_reader_loop(self) -> None:
        consecutive_failures = 0
        while not self._reader_stop.is_set():
            with self._lock:
                capture = self._capture
            if capture is None:
                return

            try:
                received, frame = capture.read()
            except Exception:
                received, frame = False, None

            if not received or frame is None:
                consecutive_failures += 1
                self._set_last_error("CAMERA_READ_FAILED")
                if consecutive_failures >= 10:
                    self._reader_stop.set()
                    with self._frame_condition:
                        self._frame_condition.notify_all()
                    return
                self._reader_stop.wait(0.05)
                continue

            consecutive_failures = 0
            with self._frame_condition:
                self._frame_sequence += 1
                frame_item = (self._frame_sequence, frame)
                self._latest_frame = frame
                self._frame_history.append(frame_item)
                self._frame_condition.notify_all()
            self._set_last_error(None)

    def _next_detection_frame(
        self,
        after_sequence: int | None,
        *,
        timeout: float,
    ) -> tuple[int, Any] | None:
        deadline = time.monotonic() + timeout
        with self._frame_condition:
            while True:
                for sequence, frame in self._frame_history:
                    if after_sequence is None or sequence > after_sequence:
                        return sequence, frame
                if self._reader_stop.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._frame_condition.wait(remaining)

    def _latest_frame_copy(
        self,
        after_sequence: int | None,
        timeout: float,
    ) -> tuple[int, Any] | None:
        deadline = time.monotonic() + timeout
        with self._frame_condition:
            while self._latest_frame is None or (
                after_sequence is not None
                and self._frame_sequence <= after_sequence
            ):
                if self._reader_stop.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._frame_condition.wait(remaining)

            frame = self._latest_frame
            return self._frame_sequence, frame.copy()

    def _detect_markers(self, frame: Any) -> tuple[Sequence[Any], Any]:
        with self._detector_lock:
            if self._detector is not None:
                corners, marker_ids, _ = self._detector.detectMarkers(frame)
            else:
                corners, marker_ids, _ = self._cv2.aruco.detectMarkers(
                    frame,
                    self._dictionary,
                    parameters=self._parameters,
                )
        return corners, marker_ids

    def _draw_preview_overlay(self, frame: Any) -> Any:
        # _latest_frame_copy already detached this frame from the reader buffer.
        preview = frame
        corners, marker_ids = self._detect_markers(frame)
        flattened_ids = _flatten_marker_ids(marker_ids)

        if flattened_ids:
            try:
                self._cv2.aruco.drawDetectedMarkers(
                    preview,
                    corners,
                    marker_ids,
                )
            except Exception:
                pass

        for marker_id, marker_corners in zip(
            flattened_ids,
            corners,
            strict=False,
        ):
            x, y = _first_corner(marker_corners)
            area = int(round(_polygon_area(marker_corners)))
            self._draw_text(preview, f"ID {marker_id}  area {area}", x, y - 8)

        height, width = frame.shape[:2]
        self._draw_text(preview, f"{width}x{height}", 10, 24)
        return preview

    def _draw_text(self, frame: Any, text: str, x: int, y: int) -> None:
        self._cv2.putText(
            frame,
            text,
            (max(0, x), max(18, y)),
            self._cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            self._cv2.LINE_AA,
        )

    def _camera_is_available(self) -> bool:
        with self._lock:
            return self._camera_is_open() and self._reader_is_running()

    def _reader_is_running(self) -> bool:
        thread = self._reader_thread
        return bool(thread is not None and thread.is_alive())

    def _set_last_error(self, error: str | None) -> None:
        with self._lock:
            self._last_error = error

    def _reset_frame_buffer(self) -> None:
        with self._frame_condition:
            self._latest_frame = None
            self._frame_sequence = 0
            self._frame_history.clear()
            self._last_detection_sequence = None
            self._frame_condition.notify_all()

    def _camera_is_open(self) -> bool:
        if self._capture is None:
            return False
        try:
            return bool(self._capture.isOpened())
        except Exception:
            return False

    def _set_capture_dimensions(self) -> None:
        if self._capture is None or self._cv2 is None:
            return
        try:
            self._capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, self.settings.width)
            self._capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self.settings.height)
        except Exception:
            # Resolution negotiation is optional; an open camera remains usable.
            pass

    def _release_capture(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            pass

    def _reset_confirmation(self) -> None:
        with self._confirmation_lock:
            self._candidate_id = None
            self._candidate_frames = 0


def _later_sequence(
    first: int | None,
    second: int | None,
) -> int | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _mjpeg_part(jpeg: bytes) -> bytes:
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
        + jpeg
        + b"\r\n"
    )


def _first_corner(corners: Any) -> tuple[int, int]:
    points = corners.tolist() if hasattr(corners, "tolist") else corners
    while (
        isinstance(points, Sequence)
        and len(points) == 1
        and isinstance(points[0], Sequence)
    ):
        points = points[0]
    if not isinstance(points, Sequence) or not points:
        return 0, 0
    return int(round(float(points[0][0]))), int(round(float(points[0][1])))


def _flatten_marker_ids(marker_ids: Any) -> list[int]:
    if marker_ids is None:
        return []
    if hasattr(marker_ids, "flatten"):
        return [int(marker_id) for marker_id in marker_ids.flatten()]

    flattened: list[int] = []

    def collect(value: Any) -> None:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                collect(item)
        else:
            flattened.append(int(value))

    collect(marker_ids)
    return flattened


def _polygon_area(corners: Any) -> float:
    points = corners.tolist() if hasattr(corners, "tolist") else corners
    while (
        isinstance(points, Sequence)
        and len(points) == 1
        and isinstance(points[0], Sequence)
    ):
        points = points[0]

    if not isinstance(points, Sequence) or len(points) < 3:
        return 0.0

    coordinates = [(float(point[0]), float(point[1])) for point in points]
    area = 0.0
    for index, (x1, y1) in enumerate(coordinates):
        x2, y2 = coordinates[(index + 1) % len(coordinates)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) / 2.0


def _read_bool_setting(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _read_positive_int_setting(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _read_positive_float_setting(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _read_min_area_ratio_setting(name: str, default: float) -> float:
    parsed = _read_positive_float_setting(name, default)
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1")
    return parsed
