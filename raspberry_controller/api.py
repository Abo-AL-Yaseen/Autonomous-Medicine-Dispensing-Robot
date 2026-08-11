"""FastAPI service that exposes the Raspberry Pi hardware controller."""

from __future__ import annotations

import os
import threading
from math import ceil
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictInt, model_validator

from .database import SessionLocal, init_db
from .hardware_controller import (
    ARDUINO_UNO_BAUD_RATE,
    ARDUINO_UNO_PORT,
    ESP32_BAUD_RATE,
    ESP32_PORT,
    HardwareControllerError,
    RobotHardwareController,
    SerialController,
)
from .navigation.engine import NavigationService
from .schemas.mission import (
    MissionCreateRequest,
    MissionStartRequest,
    MissionStatusResponse,
)
from .services.camera import ArucoCameraService, CameraSettings
from .services.mission_service import MissionService
from .services.laravel_api_client import ClaimedMission, LaravelApiClient
from .services.mission_executor import (
    MissionExecutor,
    MissionRouteUnavailableError,
    MissionStartResult,
)
from .services.navigation import NavigationMapError, RoutePlan, UnknownMarkerError
from .services.navigation.coordinator import (
    NavigationCoordinator,
    NavigationCoordinatorSettings,
)
from .services.mission_scheduler import (
    LaravelMissionClient,
    MissionScheduler,
    MissionSchedulerLoop,
    SchedulerSettings,
)


API_NAME = "Autonomous Medicine Dispensing Robot Hardware API"
API_VERSION = "1.0.0"
DEFAULT_ESP32_STARTUP_DELAY = 2.0
DEFAULT_ARDUINO_STARTUP_DELAY = 2.0
DEFAULT_READ_TIMEOUT = 2.0
DEFAULT_WATER_FLOW_ML_PER_SECOND = 0.0
DEFAULT_ROBOT_TIMEZONE = "Asia/Hebron"

ResultType = TypeVar("ResultType")
ControllerFactory = Callable[["HardwareSettings"], RobotHardwareController]
LaravelClientFactory = Callable[[SchedulerSettings], LaravelMissionClient]
CameraFactory = Callable[[CameraSettings], ArucoCameraService]


@dataclass(frozen=True)
class HardwareSettings:
    """Serial settings loaded when the application starts."""

    esp32_port: str
    arduino_port: str
    esp32_startup_delay: float
    arduino_startup_delay: float
    read_timeout: float
    water_flow_ml_per_second: float
    robot_timezone: str

    @classmethod
    def from_environment(cls) -> "HardwareSettings":
        return cls(
            esp32_port=os.getenv("ESP32_PORT", ESP32_PORT),
            arduino_port=os.getenv("ARDUINO_PORT", ARDUINO_UNO_PORT),
            esp32_startup_delay=_read_float_setting(
                "ESP32_STARTUP_DELAY",
                DEFAULT_ESP32_STARTUP_DELAY,
                allow_zero=True,
            ),
            arduino_startup_delay=_read_float_setting(
                "ARDUINO_STARTUP_DELAY",
                DEFAULT_ARDUINO_STARTUP_DELAY,
                allow_zero=True,
            ),
            read_timeout=_read_float_setting(
                "READ_TIMEOUT",
                DEFAULT_READ_TIMEOUT,
                allow_zero=False,
            ),
            water_flow_ml_per_second=_read_float_setting(
                "WATER_FLOW_ML_PER_SECOND",
                DEFAULT_WATER_FLOW_ML_PER_SECOND,
                allow_zero=True,
            ),
            robot_timezone=os.getenv("ROBOT_TIMEZONE", DEFAULT_ROBOT_TIMEZONE),
        )


class DispenseRequest(BaseModel):
    """Validated pill quantities for a single dispensing request."""

    box1: StrictInt = Field(ge=0, le=10)
    box2: StrictInt = Field(ge=0, le=10)

    @model_validator(mode="after")
    def require_at_least_one_pill(self) -> "DispenseRequest":
        if self.box1 == 0 and self.box2 == 0:
            raise ValueError("at least one box must request a pill")
        return self


class WaterDispenseRequest(BaseModel):
    """Requested water amount; delivery remains calibrated-time based."""

    amount_ml: StrictInt = Field(ge=1, le=1000)


class NavigationDecisionPreviewRequest(BaseModel):
    """A marker observation used only for read-only route diagnostics."""

    marker_id: StrictInt = Field(ge=0)


class WaterCalibrationError(ValueError):
    """Raised when no measured pump flow calibration is configured."""


class WaterDurationError(ValueError):
    """Raised when calibration would exceed the firmware safety window."""


def _read_float_setting(name: str, default: float, *, allow_zero: bool) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc

    minimum_is_valid = value >= 0 if allow_zero else value > 0
    if not minimum_is_valid:
        comparison = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {comparison}")
    return value


def calculate_water_duration_ms(amount_ml: int, flow_ml_per_second: float) -> int:
    """Convert requested ml to a bounded pump duration using measured calibration."""

    if flow_ml_per_second <= 0:
        raise WaterCalibrationError("water flow calibration is not configured")

    duration_ms = ceil((amount_ml / flow_ml_per_second) * 1000)
    if not (
        RobotHardwareController.WATER_MIN_DURATION_MS
        <= duration_ms
        <= RobotHardwareController.WATER_MAX_DURATION_MS
    ):
        raise WaterDurationError("calculated pump duration is outside safe limits")

    return duration_ms


def build_hardware_controller(settings: HardwareSettings) -> RobotHardwareController:
    """Create the existing serial controllers from API configuration."""

    esp32 = SerialController(
        settings.esp32_port,
        ESP32_BAUD_RATE,
        startup_delay=settings.esp32_startup_delay,
        read_timeout=settings.read_timeout,
    )
    arduino_uno = SerialController(
        settings.arduino_port,
        ARDUINO_UNO_BAUD_RATE,
        startup_delay=settings.arduino_startup_delay,
        read_timeout=settings.read_timeout,
    )
    return RobotHardwareController(esp32=esp32, arduino_uno=arduino_uno)


def build_laravel_client(settings: SchedulerSettings) -> LaravelApiClient:
    """Create the HTTP-only client for Laravel mission claiming."""

    return LaravelApiClient(
        settings.laravel_api_url,
        settings.laravel_api_timeout_seconds,
    )


def build_camera_service(settings: CameraSettings) -> ArucoCameraService:
    """Create the read-only camera service without opening serial hardware."""

    return ArucoCameraService(settings)


def create_app(
    controller_factory: ControllerFactory = build_hardware_controller,
    laravel_client_factory: LaravelClientFactory = build_laravel_client,
    camera_factory: CameraFactory = build_camera_service,
) -> FastAPI:
    """Create an API application, optionally with an injected test controller."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        init_db()

        settings = HardwareSettings.from_environment()
        scheduler_settings = SchedulerSettings.from_environment()
        camera_settings = CameraSettings.from_environment()
        navigation_settings = NavigationCoordinatorSettings.from_environment()
        controller = controller_factory(settings)
        hardware_lock = threading.Lock()
        laravel_client = laravel_client_factory(scheduler_settings)
        camera_service = camera_factory(camera_settings)

        application.state.hardware_controller = controller
        application.state.hardware_lock = hardware_lock
        application.state.hardware_connected = False
        application.state.hardware_settings = settings
        application.state.camera_service = camera_service

        def hardware_available() -> bool:
            return bool(application.state.hardware_connected)

        def read_rtc() -> datetime:
            if not application.state.hardware_connected:
                raise HardwareControllerError("robot hardware is disconnected")
            with hardware_lock:
                return controller.get_rtc_datetime()

        def start_executor_line_follow() -> str:
            if not application.state.hardware_connected:
                raise HardwareControllerError("robot hardware is disconnected")
            with hardware_lock:
                return controller.start_line_follow()

        def stop_executor_line_follow() -> str:
            if not application.state.hardware_connected:
                raise HardwareControllerError("robot hardware is disconnected")
            with hardware_lock:
                return controller.stop_line_follow()

        def run_navigation_hardware(operation: Callable[[], str]) -> str:
            if not application.state.hardware_connected:
                raise HardwareControllerError("robot hardware is disconnected")
            with hardware_lock:
                return operation()

        executor = MissionExecutor(
            hardware_available=hardware_available,
            start_line_follow=start_executor_line_follow,
            stop_line_follow=stop_executor_line_follow,
            mark_mission_in_progress=laravel_client.start_claimed_mission,
            load_navigation_map=laravel_client.get_navigation_map,
            auto_execution_enabled=scheduler_settings.auto_execution_enabled,
        )

        scheduler = MissionScheduler(
            hardware_available=hardware_available,
            read_rtc=read_rtc,
            laravel_client=laravel_client,
            executor=executor,
            timezone_name=settings.robot_timezone,
        )
        scheduler_loop = MissionSchedulerLoop(
            scheduler,
            enabled=scheduler_settings.enabled,
            interval_seconds=scheduler_settings.interval_seconds,
        )
        navigation_coordinator = NavigationCoordinator(
            settings=navigation_settings,
            executor=executor,
            camera_service=camera_service,
            next_serial_event=controller.get_esp32_event,
            intersection_left=lambda: run_navigation_hardware(
                controller.intersection_left
            ),
            intersection_right=lambda: run_navigation_hardware(
                controller.intersection_right
            ),
            intersection_straight=lambda: run_navigation_hardware(
                controller.intersection_straight
            ),
            stop_line_follow=lambda: run_navigation_hardware(
                controller.stop_line_follow
            ),
        )
        application.state.mission_executor = executor
        application.state.mission_scheduler = scheduler
        application.state.mission_scheduler_loop = scheduler_loop
        application.state.navigation_coordinator = navigation_coordinator

        try:
            with hardware_lock:
                controller.connect()
            application.state.hardware_connected = True
        except HardwareControllerError:
            # Keep /health available even when hardware is disconnected.
            application.state.hardware_connected = False

        try:
            camera_service.start()
        except Exception:
            # Camera availability is independent from robot serial startup.
            pass

        navigation_coordinator.start()
        scheduler_loop.start()

        try:
            yield
        finally:
            scheduler_loop.stop()
            navigation_coordinator.stop()
            try:
                camera_service.close()
            except Exception:
                pass
            try:
                laravel_client.close()
            finally:
                try:
                    with hardware_lock:
                        controller.close()
                except HardwareControllerError:
                    pass
                finally:
                    application.state.hardware_connected = False

    application = FastAPI(
        title=API_NAME,
        version=API_VERSION,
        lifespan=lifespan,
    )
    # Legacy SQLAlchemy mission routes remain available for compatibility only.
    # The new scheduler/executor path never reads or writes hospital.db.
    application.state.mission_service = MissionService()

    @application.get("/")
    def api_information() -> dict[str, object]:
        return {
            "name": API_NAME,
            "version": API_VERSION,
            "endpoints": [
                "/",
                "/health",
                "/camera/status",
                "/camera/detect",
                "/camera/stream",
                "/ping",
                "/status",
                "/rtc",
                "/scheduler/status",
                "/scheduler/tick",
                "/executor/status",
                "/executor/start",
                "/dispense",
                "/water/dispense",
                "/movement/forward",
                "/movement/backward",
                "/movement/left",
                "/movement/right",
                "/movement/stop",
                "/movement/manual/forward",
                "/movement/manual/backward",
                "/movement/manual/left",
                "/movement/manual/right",
                "/movement/manual/forward-left",
                "/movement/manual/forward-right",
                "/movement/manual/backward-left",
                "/movement/manual/backward-right",
                "/movement/manual/stop",
                "/line/sensors",
                "/line/status",
                "/line/start",
                "/line/stop",
                "/navigation/intersection/left",
                "/navigation/intersection/right",
                "/navigation/intersection/straight",
                "/navigation/u-turn",
                "/navigation/route/current",
                "/navigation/decision/preview",
                "/navigation/status",
                "/navigation/test/intersection-event",
                "/missions",
                "/missions/{id}",
                "/missions/{id}/start",
                "/missions/{id}/complete",
                "/missions/{id}/cancel",
                "/docs",
            ],
        }

    @application.get("/health")
    def health(request: Request) -> dict[str, object]:
        camera_service: ArucoCameraService = request.app.state.camera_service
        return {
            "status": "running",
            "hardware_connected": bool(request.app.state.hardware_connected),
            "camera_available": bool(camera_service.status()["camera_available"]),
        }

    @application.get("/camera/status")
    def camera_status(request: Request) -> dict[str, object]:
        camera_service: ArucoCameraService = request.app.state.camera_service
        return camera_service.status()

    @application.post("/camera/detect")
    def camera_detect(request: Request) -> dict[str, object]:
        camera_service: ArucoCameraService = request.app.state.camera_service
        return camera_service.detect().as_dict()

    @application.get("/camera/stream")
    def camera_stream(request: Request) -> StreamingResponse:
        camera_service: ArucoCameraService = request.app.state.camera_service
        first_frame = camera_service.get_preview_jpeg(timeout=1.0)
        if first_frame is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "CAMERA_UNAVAILABLE"},
            )
        return StreamingResponse(
            camera_service.mjpeg_stream(first_frame),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @application.get("/ping")
    def ping(request: Request) -> dict[str, object]:
        responses = _run_hardware_operation(
            request,
            lambda controller: controller.ping_all(),
        )
        return {"success": True, "responses": responses}

    @application.get("/status")
    def status(request: Request) -> dict[str, object]:
        statuses = _run_hardware_operation(
            request,
            lambda controller: controller.get_all_statuses(),
        )
        return {"success": True, "statuses": statuses}

    @application.get("/rtc")
    def rtc(request: Request) -> dict[str, object]:
        rtc_datetime = _run_hardware_operation(
            request,
            lambda controller: controller.get_rtc_datetime(),
        )
        settings: HardwareSettings = request.app.state.hardware_settings
        return {
            "success": True,
            "datetime": rtc_datetime.isoformat(timespec="seconds"),
            "source": "DS1302",
            "timezone": settings.robot_timezone,
        }

    @application.get("/scheduler/status")
    def scheduler_status(request: Request) -> dict[str, object]:
        scheduler_loop: MissionSchedulerLoop = (
            request.app.state.mission_scheduler_loop
        )
        return scheduler_loop.status()

    @application.post("/scheduler/tick")
    def scheduler_tick(request: Request) -> dict[str, object]:
        scheduler: MissionScheduler = request.app.state.mission_scheduler
        executor: MissionExecutor = request.app.state.mission_executor
        result = scheduler.tick()
        return {
            **result.as_dict(),
            "executor": executor.status(),
        }

    @application.get("/executor/status")
    def executor_status(request: Request) -> dict[str, object]:
        executor: MissionExecutor = request.app.state.mission_executor
        return executor.status()

    @application.post("/executor/start")
    def executor_start(request: Request) -> JSONResponse:
        executor: MissionExecutor = request.app.state.mission_executor
        result = executor.start_ready_mission()
        status_code = {
            MissionStartResult.STARTED: 200,
            MissionStartResult.NO_READY_MISSION: 409,
            MissionStartResult.HARDWARE_UNAVAILABLE: 503,
            MissionStartResult.EXECUTOR_BUSY: 409,
            MissionStartResult.INVALID_MISSION: 422,
            MissionStartResult.LINE_FOLLOW_START_FAILED: 502,
            MissionStartResult.MISSION_STATUS_UPDATE_FAILED: 502,
        }[result.result]
        return JSONResponse(
            status_code=status_code,
            content={
                **result.as_dict(),
                "executor": executor.status(),
            },
        )

    @application.post("/dispense")
    def dispense(payload: DispenseRequest, request: Request) -> dict[str, object]:
        def dispense_requested_boxes(
            controller: RobotHardwareController,
        ) -> dict[str, dict[str, int]]:
            results: dict[str, dict[str, int]] = {}
            if payload.box1 > 0:
                results["box1"] = controller.dispense(1, payload.box1)
            if payload.box2 > 0:
                results["box2"] = controller.dispense(2, payload.box2)
            return results

        results = _run_hardware_operation(request, dispense_requested_boxes)
        return {
            "success": True,
            "requested": {"box1": payload.box1, "box2": payload.box2},
            "results": results,
        }

    @application.post("/water/dispense")
    def dispense_water(
        payload: WaterDispenseRequest,
        request: Request,
    ) -> dict[str, object]:
        settings: HardwareSettings = request.app.state.hardware_settings

        def dispense_calibrated_water(
            controller: RobotHardwareController,
        ) -> dict[str, int]:
            duration_ms = calculate_water_duration_ms(
                payload.amount_ml,
                settings.water_flow_ml_per_second,
            )
            return controller.dispense_water(duration_ms)

        result = _run_hardware_operation(request, dispense_calibrated_water)
        return {
            "success": True,
            "requested_amount_ml": payload.amount_ml,
            "delivery_basis": "calibrated_time",
            "calibration_ml_per_second": settings.water_flow_ml_per_second,
            "duration_ms": result["duration_ms"],
        }

    @application.post("/movement/forward")
    def move_forward(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "forward",
            lambda controller: controller.forward(),
        )

    @application.post("/movement/backward")
    def move_backward(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "backward",
            lambda controller: controller.backward(),
        )

    @application.post("/movement/left")
    def turn_left(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "left",
            lambda controller: controller.turn_left(),
        )

    @application.post("/movement/right")
    def turn_right(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "right",
            lambda controller: controller.turn_right(),
        )

    @application.post("/movement/stop")
    def stop(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "stop",
            lambda controller: controller.stop(),
        )

    @application.post("/movement/manual/forward")
    def manual_forward(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-forward",
            lambda controller: controller.manual_forward(),
        )

    @application.post("/movement/manual/backward")
    def manual_backward(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-backward",
            lambda controller: controller.manual_backward(),
        )

    @application.post("/movement/manual/left")
    def manual_left(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-left",
            lambda controller: controller.manual_left(),
        )

    @application.post("/movement/manual/right")
    def manual_right(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-right",
            lambda controller: controller.manual_right(),
        )

    @application.post("/movement/manual/forward-left")
    def manual_forward_left(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-forward-left",
            lambda controller: controller.manual_forward_left(),
        )

    @application.post("/movement/manual/forward-right")
    def manual_forward_right(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-forward-right",
            lambda controller: controller.manual_forward_right(),
        )

    @application.post("/movement/manual/backward-left")
    def manual_backward_left(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-backward-left",
            lambda controller: controller.manual_backward_left(),
        )

    @application.post("/movement/manual/backward-right")
    def manual_backward_right(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-backward-right",
            lambda controller: controller.manual_backward_right(),
        )

    @application.post("/movement/manual/stop")
    def manual_stop(request: Request) -> dict[str, object]:
        return _movement_response(
            request,
            "manual-stop",
            lambda controller: controller.manual_stop(),
        )

    @application.get("/line/sensors")
    def get_line_sensors(request: Request) -> dict[str, object]:
        response = _run_hardware_operation(
            request,
            lambda controller: controller.get_line_reading(),
        )
        return {"success": True, "reading": response}

    @application.get("/line/status")
    def get_line_status(request: Request) -> dict[str, object]:
        response = _run_hardware_operation(
            request,
            lambda controller: controller.get_line_status(),
        )
        return {"success": True, "status": response}

    @application.post("/line/start")
    def start_line_follow(request: Request) -> dict[str, object]:
        response = _run_hardware_operation(
            request,
            lambda controller: controller.start_line_follow(),
        )
        return {"success": True, "response": response}

    @application.post("/line/stop")
    def stop_line_follow(request: Request) -> dict[str, object]:
        response = _run_hardware_operation(
            request,
            lambda controller: controller.stop_line_follow(),
        )
        return {"success": True, "response": response}

    @application.post("/navigation/intersection/left")
    def intersection_left(request: Request) -> dict[str, object]:
        return _navigation_response(
            request,
            "left",
            lambda controller: controller.intersection_left(),
        )

    @application.post("/navigation/intersection/right")
    def intersection_right(request: Request) -> dict[str, object]:
        return _navigation_response(
            request,
            "right",
            lambda controller: controller.intersection_right(),
        )

    @application.post("/navigation/intersection/straight")
    def intersection_straight(request: Request) -> dict[str, object]:
        return _navigation_response(
            request,
            "straight",
            lambda controller: controller.intersection_straight(),
        )

    @application.post("/navigation/u-turn")
    def u_turn(request: Request) -> dict[str, object]:
        return _navigation_response(
            request,
            "u-turn",
            lambda controller: controller.u_turn(),
        )

    @application.get("/navigation/route/current")
    def current_navigation_route(
        marker_id: int,
        request: Request,
    ) -> dict[str, object]:
        executor: MissionExecutor = request.app.state.mission_executor
        mission, plan = _preview_route(executor, marker_id)
        return {
            **_route_preview_payload(mission.id, mission.room_id, plan),
            "route": [step.as_dict() for step in plan.steps],
        }

    @application.post("/navigation/decision/preview")
    def preview_navigation_decision(
        payload: NavigationDecisionPreviewRequest,
        request: Request,
    ) -> dict[str, object]:
        executor: MissionExecutor = request.app.state.mission_executor
        mission, plan = _preview_route(executor, payload.marker_id)
        return _route_preview_payload(mission.id, mission.room_id, plan)

    @application.get("/navigation/status")
    def navigation_status(request: Request) -> dict[str, object]:
        coordinator: NavigationCoordinator = (
            request.app.state.navigation_coordinator
        )
        return coordinator.status()

    @application.post("/navigation/test/intersection-event")
    def test_navigation_intersection_event(
        request: Request,
    ) -> dict[str, object]:
        coordinator: NavigationCoordinator = (
            request.app.state.navigation_coordinator
        )
        if coordinator.enabled:
            raise HTTPException(
                status_code=409,
                detail={"code": "NAVIGATION_TEST_DISABLED_WHILE_AUTO_ENABLED"},
            )
        return coordinator.preview_test_intersection()

    @application.post("/missions")
    def create_mission(payload: MissionCreateRequest, request: Request) -> dict[str, object]:
        service: MissionService = request.app.state.mission_service
        mission = service.create_mission(
            room_id=payload.room_id,
            medicine_id=payload.medicine_id,
            quantity=payload.quantity,
        )
        return {
            "id": mission.id,
            "room_id": mission.room_id,
            "medicine_id": mission.medicine_id,
            "quantity": mission.quantity,
            "status": mission.status.value,
            "created_at": mission.created_at.isoformat(),
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        }

    @application.get("/missions")
    def list_missions(request: Request) -> list[dict[str, object]]:
        service: MissionService = request.app.state.mission_service
        missions = service.get_missions()
        return [
            {
                "id": mission.id,
                "room_id": mission.room_id,
                "medicine_id": mission.medicine_id,
                "quantity": mission.quantity,
                "status": mission.status.value,
                "created_at": mission.created_at.isoformat(),
                "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
            }
            for mission in missions
        ]

    @application.get("/missions/{mission_id}")
    def get_mission(mission_id: int, request: Request) -> dict[str, object]:
        service: MissionService = request.app.state.mission_service
        mission = service.get_mission(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})

        return {
            "id": mission.id,
            "room_id": mission.room_id,
            "medicine_id": mission.medicine_id,
            "quantity": mission.quantity,
            "status": mission.status.value,
            "created_at": mission.created_at.isoformat(),
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        }

    @application.post("/missions/{mission_id}/start")
    def start_mission(
        mission_id: int,
        payload: MissionStartRequest,
        request: Request,
    ) -> MissionStatusResponse:
        service: MissionService = request.app.state.mission_service
        try:
            result = service.start_mission(
                mission_id,
                current_node=payload.current_node if payload.current_node is not None else 0,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc

        return MissionStatusResponse(**result)

    @application.post("/missions/{mission_id}/complete")
    def complete_mission(mission_id: int, request: Request) -> dict[str, object]:
        service: MissionService = request.app.state.mission_service
        try:
            mission = service.complete_mission(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

        return {
            "id": mission.id,
            "status": mission.status.value,
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        }

    @application.post("/missions/{mission_id}/cancel")
    def cancel_mission(mission_id: int, request: Request) -> dict[str, object]:
        service: MissionService = request.app.state.mission_service
        try:
            mission = service.cancel_mission(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

        return {
            "id": mission.id,
            "status": mission.status.value,
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        }

    return application


def _movement_response(
    request: Request,
    movement: str,
    operation: Callable[[RobotHardwareController], str],
) -> dict[str, object]:
    response = _run_hardware_operation(request, operation)
    return {"success": True, "movement": movement, "response": response}


def _navigation_response(
    request: Request,
    direction: str,
    operation: Callable[[RobotHardwareController], str],
) -> dict[str, object]:
    response = _run_hardware_operation(request, operation)
    return {"success": True, "direction": direction, "response": response}


def _preview_route(
    executor: MissionExecutor,
    marker_id: int,
) -> tuple[ClaimedMission, RoutePlan]:
    try:
        return executor.plan_route(marker_id)
    except UnknownMarkerError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNKNOWN_MARKER"},
        ) from exc
    except MissionRouteUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "NO_LOADED_MISSION"},
        ) from exc
    except NavigationMapError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "NAVIGATION_MAP_INVALID"},
        ) from exc


def _route_preview_payload(
    mission_id: int,
    room_id: int,
    plan: RoutePlan,
) -> dict[str, object]:
    return {
        "success": plan.success,
        "mission_id": mission_id,
        "room_id": room_id,
        "current_node": plan.current_node.name,
        "current_marker_id": plan.current_node.marker_id,
        "destination_node": plan.destination_node.name,
        "destination_marker_id": plan.destination_node.marker_id,
        "decision": plan.decision.value,
        "next_node": plan.next_node,
    }


def _run_hardware_operation(
    request: Request,
    operation: Callable[[RobotHardwareController], ResultType],
) -> ResultType:
    """Serialize blocking hardware access and convert errors to safe HTTP responses."""

    if not request.app.state.hardware_connected:
        raise HTTPException(
            status_code=503,
            detail={"code": "HARDWARE_UNAVAILABLE"},
        )

    controller: RobotHardwareController = request.app.state.hardware_controller
    hardware_lock: threading.Lock = request.app.state.hardware_lock
    try:
        with hardware_lock:
            return operation(controller)
    except WaterCalibrationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "WATER_FLOW_NOT_CALIBRATED"},
        ) from exc
    except WaterDurationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "WATER_DURATION_OUT_OF_RANGE"},
        ) from exc
    except HardwareControllerError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "HARDWARE_COMMUNICATION_FAILED"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR"},
        ) from exc


app = create_app()
