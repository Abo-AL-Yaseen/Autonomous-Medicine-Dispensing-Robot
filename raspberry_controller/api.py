"""FastAPI service that exposes the Raspberry Pi hardware controller."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, StrictInt, model_validator

from .hardware_controller import (
    ARDUINO_UNO_BAUD_RATE,
    ARDUINO_UNO_PORT,
    ESP32_BAUD_RATE,
    ESP32_PORT,
    HardwareControllerError,
    RobotHardwareController,
    SerialController,
)


API_NAME = "Autonomous Medicine Dispensing Robot Hardware API"
API_VERSION = "1.0.0"
DEFAULT_ESP32_STARTUP_DELAY = 2.0
DEFAULT_ARDUINO_STARTUP_DELAY = 2.0
DEFAULT_READ_TIMEOUT = 2.0

ResultType = TypeVar("ResultType")
ControllerFactory = Callable[["HardwareSettings"], RobotHardwareController]


@dataclass(frozen=True)
class HardwareSettings:
    """Serial settings loaded when the application starts."""

    esp32_port: str
    arduino_port: str
    esp32_startup_delay: float
    arduino_startup_delay: float
    read_timeout: float

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


def create_app(
    controller_factory: ControllerFactory = build_hardware_controller,
) -> FastAPI:
    """Create an API application, optionally with an injected test controller."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = HardwareSettings.from_environment()
        controller = controller_factory(settings)
        hardware_lock = threading.Lock()

        application.state.hardware_controller = controller
        application.state.hardware_lock = hardware_lock
        application.state.hardware_connected = False

        try:
            with hardware_lock:
                controller.connect()
            application.state.hardware_connected = True
        except HardwareControllerError:
            # Keep /health available even when hardware is disconnected.
            application.state.hardware_connected = False

        try:
            yield
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

    @application.get("/")
    def api_information() -> dict[str, object]:
        return {
            "name": API_NAME,
            "version": API_VERSION,
            "endpoints": [
                "/",
                "/health",
                "/ping",
                "/status",
                "/dispense",
                "/movement/forward",
                "/movement/backward",
                "/movement/left",
                "/movement/right",
                "/movement/stop",
                "/line/sensors",
                "/line/status",
                "/line/start",
                "/line/stop",
                "/navigation/intersection/left",
                "/navigation/intersection/right",
                "/navigation/intersection/straight",
                "/navigation/u-turn",
                "/docs",
            ],
        }

    @application.get("/health")
    def health(request: Request) -> dict[str, object]:
        return {
            "status": "running",
            "hardware_connected": bool(request.app.state.hardware_connected),
        }

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
