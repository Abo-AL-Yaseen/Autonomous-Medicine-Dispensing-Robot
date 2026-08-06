"""Run USB-camera ArUco detection for the active robot mission."""

from __future__ import annotations

import logging

import cv2

from ..api import HardwareSettings, build_hardware_controller
from ..navigation.engine import NavigationService
from ..services.mission_service import MissionService
from .mission_navigation_integration import MissionNavigationIntegration


logger = logging.getLogger(__name__)
ARUCO_DICTIONARY = cv2.aruco.DICT_4X4_50


def main() -> None:
    """Detect USB-camera markers and pass them to the integration layer."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    controller = build_hardware_controller(HardwareSettings.from_environment())
    mission_service = MissionService()
    integration = MissionNavigationIntegration(
        controller,
        mission_service,
        NavigationService(),
    )
    camera = cv2.VideoCapture(2)

    if not camera.isOpened():
        camera.release()
        raise RuntimeError("Unable to open the default USB camera")

    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARY)
    parameters = (
        cv2.aruco.DetectorParameters()
        if hasattr(cv2.aruco, "DetectorParameters")
        else cv2.aruco.DetectorParameters_create()
    )
    detector = (
        cv2.aruco.ArucoDetector(dictionary, parameters)
        if hasattr(cv2.aruco, "ArucoDetector")
        else None
    )

    try:
        controller.connect()
        while True:
            received, frame = camera.read()
            if not received:
                logger.warning("Unable to read frame from USB camera")
                continue

            if detector is None:
                corners, marker_ids, _ = cv2.aruco.detectMarkers(
                    frame,
                    dictionary,
                    parameters=parameters,
                )
            else:
                corners, marker_ids, _ = detector.detectMarkers(frame)
            if marker_ids is not None:
                cv2.aruco.drawDetectedMarkers(frame, corners, marker_ids)
                for marker_id in marker_ids.flatten():
                    integration.process_marker(int(marker_id))

            cv2.imshow("Medicine Robot ArUco Camera", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()
        controller.close()


if __name__ == "__main__":
    main()
