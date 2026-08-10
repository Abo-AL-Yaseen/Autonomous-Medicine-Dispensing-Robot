"""Software-only tests for the read-only ArUco camera service."""

from __future__ import annotations

from typing import Any

import pytest

from raspberry_controller.services.camera import (
    APPROVED_MARKERS,
    ArucoCameraService,
    CameraSettings,
)


def square(size: int, *, offset: int = 0) -> list[list[list[int]]]:
    return [[
        [offset, offset],
        [offset + size, offset],
        [offset + size, offset + size],
        [offset, offset + size],
    ]]


class FakeCapture:
    def __init__(self, frames: list[Any], *, opened: bool = True) -> None:
        self.frames = list(frames)
        self.opened = opened
        self.released = False
        self.settings: list[tuple[int, int]] = []

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def read(self) -> tuple[bool, Any]:
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def set(self, property_id: int, value: int) -> bool:
        self.settings.append((property_id, value))
        return True

    def release(self) -> None:
        self.released = True


class FakeDetector:
    def detectMarkers(self, frame: Any) -> Any:
        return frame


class FakeAruco:
    DICT_4X4_50 = 50

    @staticmethod
    def getPredefinedDictionary(dictionary_id: int) -> int:
        return dictionary_id

    @staticmethod
    def DetectorParameters() -> object:
        return object()

    @staticmethod
    def ArucoDetector(dictionary: Any, parameters: Any) -> FakeDetector:
        return FakeDetector()


class FakeCv2:
    CAP_V4L2 = 200
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    aruco = FakeAruco()


def build_service(
    capture: FakeCapture,
    *,
    confirm_frames: int = 3,
    min_marker_area: float = 100.0,
) -> ArucoCameraService:
    return ArucoCameraService(
        CameraSettings(
            enabled=True,
            device="/dev/video0",
            width=640,
            height=480,
            confirm_frames=confirm_frames,
            min_marker_area=min_marker_area,
        ),
        cv2_module=FakeCv2(),
        capture_factory=lambda cv2_module, device: capture,
    )


def test_camera_settings_are_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAMERA_ENABLED", "true")
    monkeypatch.setenv("CAMERA_DEVICE", "/dev/video0")
    monkeypatch.setenv("CAMERA_WIDTH", "1280")
    monkeypatch.setenv("CAMERA_HEIGHT", "720")
    monkeypatch.setenv("ARUCO_CONFIRM_FRAMES", "4")
    monkeypatch.setenv("ARUCO_MIN_MARKER_AREA", "3200.5")

    assert CameraSettings.from_environment() == CameraSettings(
        enabled=True,
        device="/dev/video0",
        width=1280,
        height=720,
        confirm_frames=4,
        min_marker_area=3200.5,
    )


def test_camera_unavailable_is_reported_without_raising() -> None:
    capture = FakeCapture([], opened=False)
    service = build_service(capture)

    assert service.start() is False
    assert capture.released is True
    assert service.status()["camera_available"] is False
    assert service.detect().as_dict() == {
        "camera_available": False,
        "detected": False,
        "confirmed": False,
        "marker_id": None,
        "node_name": None,
        "marker_type": None,
        "area": None,
        "consecutive_frames": 0,
    }


def test_no_marker_is_not_detected() -> None:
    capture = FakeCapture([([], None, [])])
    service = build_service(capture, confirm_frames=1)

    assert service.start() is True
    result = service.detect()

    assert result.camera_available is True
    assert result.detected is False
    assert result.confirmed is False


def test_unapproved_marker_is_ignored() -> None:
    service = build_service(FakeCapture([]), confirm_frames=1)

    result = service.process_detections([[6]], [square(100)])

    assert result.detected is False
    assert result.marker_id is None


@pytest.mark.parametrize(
    ("marker_id", "node_name", "marker_type"),
    [
        (0, "NODE_0", "intersection"),
        (1, "NODE_1", "intersection"),
        (2, "NODE_2", "intersection"),
        (11, "ROOM_1", "room"),
        (12, "ROOM_2", "room"),
        (13, "ROOM_3", "room"),
        (14, "ROOM_4", "room"),
        (15, "ROOM_5", "room"),
    ],
)
def test_approved_marker_mapping(
    marker_id: int,
    node_name: str,
    marker_type: str,
) -> None:
    service = build_service(FakeCapture([]), confirm_frames=1)

    result = service.process_detections([[marker_id]], [square(50)])

    assert result.confirmed is True
    assert result.marker_id == marker_id
    assert result.node_name == node_name
    assert result.marker_type == marker_type
    assert result.area == 2500


def test_same_marker_is_confirmed_after_configured_consecutive_frames() -> None:
    frame = ([square(50)], [[1]], [])
    capture = FakeCapture([frame, frame, frame])
    service = build_service(capture, confirm_frames=3)

    assert service.start() is True
    result = service.detect()

    assert result.confirmed is True
    assert result.marker_id == 1
    assert result.consecutive_frames == 3


def test_marker_is_not_confirmed_with_insufficient_consecutive_frames() -> None:
    service = build_service(FakeCapture([]), confirm_frames=3)

    first = service.process_detections([[2]], [square(50)])
    second = service.process_detections([[2]], [square(50)])

    assert first.confirmed is False
    assert second.confirmed is False
    assert second.consecutive_frames == 2


def test_tiny_marker_is_rejected_by_minimum_area() -> None:
    service = build_service(
        FakeCapture([]),
        confirm_frames=1,
        min_marker_area=2500,
    )

    result = service.process_detections([[1]], [square(20)])

    assert result.detected is False
    assert result.confirmed is False


def test_largest_approved_marker_is_the_only_selected_candidate() -> None:
    service = build_service(FakeCapture([]), confirm_frames=1)

    result = service.process_detections(
        [[1], [11], [49]],
        [square(50), square(70), square(120)],
    )

    assert result.marker_id == 11
    assert result.node_name == "ROOM_1"
    assert result.area == 4900


def test_camera_service_releases_camera_and_never_touches_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serial_calls: list[str] = []

    def fail_if_serial_connects(*args: object, **kwargs: object) -> None:
        serial_calls.append("connect")
        raise AssertionError("camera service must never open serial")

    monkeypatch.setattr(
        "raspberry_controller.hardware_controller.SerialController.open",
        fail_if_serial_connects,
    )
    frame = ([square(50)], [[0]], [])
    capture = FakeCapture([frame])
    service = build_service(capture, confirm_frames=1)

    assert service.start() is True
    assert service.detect().marker_id in APPROVED_MARKERS
    service.close()

    assert serial_calls == []
    assert capture.released is True
