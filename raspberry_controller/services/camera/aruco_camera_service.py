"""Read-only USB camera service for confirmed ArUco marker diagnostics."""

from __future__ import annotations

import importlib
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any


ARUCO_DICTIONARY_NAME = "DICT_4X4_50"
DEFAULT_CAMERA_DEVICE = "/dev/video0"
DEFAULT_CAMERA_WIDTH = 640
DEFAULT_CAMERA_HEIGHT = 480
DEFAULT_CONFIRM_FRAMES = 3
DEFAULT_MIN_MARKER_AREA = 2500.0

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

    def start(self) -> bool:
        """Open and configure the camera without propagating availability failures."""

        with self._lock:
            if not self.settings.enabled:
                self._last_error = None
                return False

            if self._camera_is_open():
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
                self._last_error = None
                return True
            except Exception:
                self._release_capture()
                self._last_error = "CAMERA_INITIALIZATION_FAILED"
                return False

    def close(self) -> None:
        """Release the camera cleanly and reset confirmation state."""

        with self._lock:
            self._release_capture()
            self._reset_confirmation()

    def status(self) -> dict[str, object]:
        with self._lock:
            camera_open = self._camera_is_open()
            return {
                "enabled": self.settings.enabled,
                "device": self.settings.device,
                "camera_open": camera_open,
                "camera_available": camera_open,
                "dictionary": ARUCO_DICTIONARY_NAME,
                "width": self.settings.width,
                "height": self.settings.height,
                "confirm_frames": self.settings.confirm_frames,
                "min_marker_area": self.settings.min_marker_area,
                "error": self._last_error,
            }

    def detect(self) -> MarkerDetectionResult:
        """Read enough frames for one candidate to satisfy confirmation."""

        with self._lock:
            if not self._camera_is_open():
                return MarkerDetectionResult(
                    camera_available=False,
                    detected=False,
                    confirmed=False,
                )

            result = MarkerDetectionResult(
                camera_available=True,
                detected=False,
                confirmed=False,
            )
            for _ in range(self.settings.confirm_frames):
                try:
                    result = self._detect_next_frame()
                except Exception:
                    self._last_error = "CAMERA_READ_FAILED"
                    self._reset_confirmation()
                    return MarkerDetectionResult(
                        camera_available=self._camera_is_open(),
                        detected=False,
                        confirmed=False,
                    )
                if result.confirmed:
                    break

            return result

    def process_detections(
        self,
        marker_ids: Any,
        corners: Sequence[Any],
        *,
        camera_available: bool = True,
    ) -> MarkerDetectionResult:
        """Filter one detector result and update consecutive-frame state."""

        observations: list[tuple[int, int]] = []
        flattened_ids = _flatten_marker_ids(marker_ids)

        for marker_id, marker_corners in zip(flattened_ids, corners, strict=False):
            if marker_id not in APPROVED_MARKERS:
                continue

            area = _polygon_area(marker_corners)
            if area < self.settings.min_marker_area:
                continue

            observations.append((marker_id, int(round(area))))

        if not observations:
            self._reset_confirmation()
            return MarkerDetectionResult(
                camera_available=camera_available,
                detected=False,
                confirmed=False,
            )

        # Largest approved marker wins. Equal areas deterministically prefer
        # the lower marker ID so only one candidate can advance confirmation.
        marker_id, area = max(observations, key=lambda item: (item[1], -item[0]))
        if marker_id == self._candidate_id:
            self._candidate_frames += 1
        else:
            self._candidate_id = marker_id
            self._candidate_frames = 1

        node_name, marker_type = APPROVED_MARKERS[marker_id]
        return MarkerDetectionResult(
            camera_available=camera_available,
            detected=True,
            confirmed=self._candidate_frames >= self.settings.confirm_frames,
            marker_id=marker_id,
            node_name=node_name,
            marker_type=marker_type,
            area=area,
            consecutive_frames=self._candidate_frames,
        )

    def _detect_next_frame(self) -> MarkerDetectionResult:
        received, frame = self._capture.read()
        if not received:
            self._reset_confirmation()
            return MarkerDetectionResult(
                camera_available=True,
                detected=False,
                confirmed=False,
            )

        if self._detector is not None:
            corners, marker_ids, _ = self._detector.detectMarkers(frame)
        else:
            corners, marker_ids, _ = self._cv2.aruco.detectMarkers(
                frame,
                self._dictionary,
                parameters=self._parameters,
            )

        return self.process_detections(marker_ids, corners)

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
        self._candidate_id = None
        self._candidate_frames = 0


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
