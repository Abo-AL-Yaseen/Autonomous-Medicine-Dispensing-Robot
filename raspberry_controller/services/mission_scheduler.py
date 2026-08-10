"""Safe RTC-driven mission claiming with no movement or dispensing logic."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from ..hardware_controller import HardwareControllerError
from .laravel_api_client import (
    ClaimedMission,
    LaravelApiError,
    LaravelApiUnavailable,
)
from .navigation import PhysicalNavigationMap
from .mission_executor import MissionExecutionState, MissionExecutor


DEFAULT_LARAVEL_API_URL = "http://127.0.0.1:8000/api"
DEFAULT_LARAVEL_API_TIMEOUT_SECONDS = 2.0
DEFAULT_MISSION_SCHEDULER_INTERVAL_SECONDS = 5.0


class LaravelMissionClient(Protocol):
    def claim_due_mission(
        self,
        robot_datetime: datetime,
        timezone_name: str,
    ) -> ClaimedMission | None: ...

    def start_claimed_mission(self, mission: ClaimedMission) -> None: ...

    def get_navigation_map(self) -> PhysicalNavigationMap: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SchedulerSettings:
    laravel_api_url: str
    laravel_api_timeout_seconds: float
    enabled: bool
    interval_seconds: float
    auto_execution_enabled: bool = False

    @classmethod
    def from_environment(cls) -> "SchedulerSettings":
        return cls(
            laravel_api_url=os.getenv(
                "LARAVEL_API_URL",
                DEFAULT_LARAVEL_API_URL,
            ),
            laravel_api_timeout_seconds=_positive_float_setting(
                "LARAVEL_API_TIMEOUT_SECONDS",
                DEFAULT_LARAVEL_API_TIMEOUT_SECONDS,
            ),
            enabled=_boolean_setting("MISSION_SCHEDULER_ENABLED", False),
            interval_seconds=_positive_float_setting(
                "MISSION_SCHEDULER_INTERVAL_SECONDS",
                DEFAULT_MISSION_SCHEDULER_INTERVAL_SECONDS,
            ),
            auto_execution_enabled=_boolean_setting(
                "MISSION_AUTO_EXECUTION_ENABLED",
                False,
            ),
        )


class SchedulerResult(str, Enum):
    EXECUTOR_ACCEPT_FAILED = "EXECUTOR_ACCEPT_FAILED"
    EXECUTOR_BUSY = "EXECUTOR_BUSY"
    HARDWARE_UNAVAILABLE = "HARDWARE_UNAVAILABLE"
    INVALID_RTC = "INVALID_RTC"
    LARAVEL_UNAVAILABLE = "LARAVEL_UNAVAILABLE"
    NO_DUE_MISSION = "NO_DUE_MISSION"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"


@dataclass(frozen=True)
class SchedulerTickResult:
    result: SchedulerResult
    success: bool
    mission_id: int | None = None
    robot_datetime: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "result": self.result.value,
            "mission_id": self.mission_id,
            "robot_datetime": self.robot_datetime,
            "message": self.message,
        }


class MissionScheduler:
    """Perform one serialized RTC-read and Laravel-claim operation per tick."""

    def __init__(
        self,
        *,
        hardware_available: Callable[[], bool],
        read_rtc: Callable[[], datetime],
        laravel_client: LaravelMissionClient,
        executor: MissionExecutor,
        timezone_name: str,
    ) -> None:
        self._hardware_available = hardware_available
        self._read_rtc = read_rtc
        self._laravel_client = laravel_client
        self._executor = executor
        self._timezone_name = timezone_name
        self._tick_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._last_tick_at: str | None = None
        self._last_result: SchedulerTickResult | None = None
        self._pending_acceptance: tuple[ClaimedMission, str] | None = None

    def tick(self) -> SchedulerTickResult:
        with self._tick_lock:
            # This is deliberately the first operational check. A scheduler
            # may only read the RTC or claim from Laravel while the executor
            # is IDLE. Using a negative IDLE check also protects future busy
            # executor states without having to enumerate them here.
            if self._executor.state is not MissionExecutionState.IDLE:
                return self._record(
                    SchedulerTickResult(
                        result=SchedulerResult.EXECUTOR_BUSY,
                        success=True,
                        mission_id=self._executor.mission_id,
                        message="MissionExecutor is busy; no mission was claimed.",
                    )
                )

            # If Laravel claimed a mission but a defensive executor boundary
            # failed, retry that same in-memory mission before any RTC read or
            # new claim. This prevents silently skipping to another mission.
            if self._pending_acceptance is not None:
                mission, robot_datetime_text = self._pending_acceptance
                return self._accept_claimed_mission(
                    mission,
                    robot_datetime_text,
                )

            if not self._hardware_available():
                return self._record(
                    SchedulerTickResult(
                        result=SchedulerResult.HARDWARE_UNAVAILABLE,
                        success=False,
                        message="Robot hardware is disconnected; no mission was claimed.",
                    )
                )

            try:
                robot_datetime = self._read_rtc()
                if robot_datetime.tzinfo is not None:
                    raise ValueError("RTC must return a timezone-naive wall-clock")
            except (HardwareControllerError, ValueError) as exc:
                return self._record(
                    SchedulerTickResult(
                        result=SchedulerResult.INVALID_RTC,
                        success=False,
                        message=str(exc) or "Robot RTC could not be read.",
                    )
                )

            robot_datetime_text = robot_datetime.isoformat(timespec="seconds")
            try:
                mission = self._laravel_client.claim_due_mission(
                    robot_datetime,
                    self._timezone_name,
                )
            except (LaravelApiUnavailable, LaravelApiError) as exc:
                return self._record(
                    SchedulerTickResult(
                        result=SchedulerResult.LARAVEL_UNAVAILABLE,
                        success=False,
                        robot_datetime=robot_datetime_text,
                        message=str(exc),
                    )
                )

            if mission is None:
                return self._record(
                    SchedulerTickResult(
                        result=SchedulerResult.NO_DUE_MISSION,
                        success=True,
                        robot_datetime=robot_datetime_text,
                    )
                )

            self._pending_acceptance = (mission, robot_datetime_text)
            return self._accept_claimed_mission(
                mission,
                robot_datetime_text,
            )

    def status(self, *, enabled: bool, running: bool) -> dict[str, object]:
        with self._status_lock:
            last_result = (
                self._last_result.as_dict() if self._last_result else None
            )
            last_tick_at = self._last_tick_at

        return {
            "enabled": enabled,
            "running": running,
            **self._executor.status(),
            "pending_acceptance_mission_id": (
                self._pending_acceptance[0].id
                if self._pending_acceptance is not None
                else None
            ),
            "last_tick_at": last_tick_at,
            "last_result": last_result,
        }

    def _accept_claimed_mission(
        self,
        mission: ClaimedMission,
        robot_datetime_text: str,
    ) -> SchedulerTickResult:
        try:
            accepted = self._executor.accept(mission)
        except Exception as exc:
            return self._record(
                SchedulerTickResult(
                    result=SchedulerResult.EXECUTOR_ACCEPT_FAILED,
                    success=False,
                    mission_id=mission.id,
                    robot_datetime=robot_datetime_text,
                    message=(
                        "Mission was claimed but MissionExecutor did not accept it: "
                        f"{exc}"
                    ),
                )
            )

        if not accepted:
            return self._record(
                SchedulerTickResult(
                    result=SchedulerResult.EXECUTOR_ACCEPT_FAILED,
                    success=False,
                    mission_id=mission.id,
                    robot_datetime=robot_datetime_text,
                    message="Mission was claimed but MissionExecutor rejected it.",
                )
            )

        self._pending_acceptance = None
        return self._record(
            SchedulerTickResult(
                result=SchedulerResult.READY_FOR_EXECUTION,
                success=True,
                mission_id=mission.id,
                robot_datetime=robot_datetime_text,
            )
        )

    def _record(self, result: SchedulerTickResult) -> SchedulerTickResult:
        with self._status_lock:
            self._last_tick_at = datetime.now(timezone.utc).isoformat()
            self._last_result = result
        return result


class MissionSchedulerLoop:
    """Own at most one periodic scheduler thread in the current process."""

    def __init__(
        self,
        scheduler: MissionScheduler,
        *,
        enabled: bool,
        interval_seconds: float,
    ) -> None:
        self._scheduler = scheduler
        self.enabled = enabled
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if not self.enabled:
            return

        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="mission-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            self._stop_event.set()

        if thread and thread.is_alive():
            # RTC and Laravel operations have bounded I/O timeouts. Wait for
            # the current tick to finish so the HTTP client/controller cannot
            # be closed underneath the scheduler thread.
            thread.join()

        with self._lifecycle_lock:
            self._thread = None

    def status(self) -> dict[str, object]:
        return self._scheduler.status(
            enabled=self.enabled,
            running=self.running,
        )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._scheduler.tick()
            if self._stop_event.wait(self._interval_seconds):
                return


def _boolean_setting(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _positive_float_setting(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
