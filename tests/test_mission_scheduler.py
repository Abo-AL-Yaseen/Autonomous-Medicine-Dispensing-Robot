"""Software-only tests for RTC-driven Laravel mission claiming."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from raspberry_controller.services.laravel_api_client import (
    ClaimedMission,
    LaravelApiClient,
    LaravelApiError,
    LaravelApiUnavailable,
)
from raspberry_controller.services.mission_executor import (
    MissionExecutionState,
    MissionExecutor,
)
from raspberry_controller.services.mission_scheduler import (
    MissionScheduler,
    MissionSchedulerLoop,
    SchedulerResult,
    SchedulerSettings,
)


class FakeLaravelClient:
    def __init__(self) -> None:
        self.claimed_mission: ClaimedMission | None = None
        self.error: Exception | None = None
        self.calls: list[tuple[datetime, str]] = []
        self.closed = False

    def claim_due_mission(
        self,
        robot_datetime: datetime,
        timezone_name: str,
    ) -> ClaimedMission | None:
        self.calls.append((robot_datetime, timezone_name))
        if self.error:
            raise self.error
        return self.claimed_mission

    def close(self) -> None:
        self.closed = True


class SafeSchedulerHardware:
    def __init__(self) -> None:
        self.available = True
        self.rtc = datetime(2026, 8, 9, 21, 40, 0)
        self.rtc_error: Exception | None = None
        self.rtc_calls = 0
        self.movement_calls: list[str] = []
        self.line_calls: list[str] = []
        self.camera_calls: list[str] = []
        self.dispense_calls: list[object] = []
        self.water_calls: list[object] = []

    def read_rtc(self) -> datetime:
        self.rtc_calls += 1
        if self.rtc_error:
            raise self.rtc_error
        return self.rtc


def build_scheduler(
    hardware: SafeSchedulerHardware,
    laravel: FakeLaravelClient,
    executor: MissionExecutor | None = None,
) -> tuple[MissionScheduler, MissionExecutor]:
    executor = executor or MissionExecutor()
    scheduler = MissionScheduler(
        hardware_available=lambda: hardware.available,
        read_rtc=hardware.read_rtc,
        laravel_client=laravel,
        executor=executor,
        timezone_name="Asia/Hebron",
    )
    return scheduler, executor


def test_scheduler_does_not_claim_when_hardware_is_unavailable() -> None:
    hardware = SafeSchedulerHardware()
    hardware.available = False
    laravel = FakeLaravelClient()
    scheduler, executor = build_scheduler(hardware, laravel)

    result = scheduler.tick()

    assert result.result is SchedulerResult.HARDWARE_UNAVAILABLE
    assert executor.state is MissionExecutionState.IDLE
    assert hardware.rtc_calls == 0
    assert laravel.calls == []


def test_scheduler_does_not_claim_when_rtc_is_invalid() -> None:
    hardware = SafeSchedulerHardware()
    hardware.rtc_error = ValueError("invalid RTC date or time")
    laravel = FakeLaravelClient()
    scheduler, executor = build_scheduler(hardware, laravel)

    result = scheduler.tick()

    assert result.result is SchedulerResult.INVALID_RTC
    assert executor.state is MissionExecutionState.IDLE
    assert laravel.calls == []


def test_scheduler_handles_laravel_unavailable_without_execution() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    laravel.error = LaravelApiUnavailable("timeout")
    scheduler, executor = build_scheduler(hardware, laravel)

    result = scheduler.tick()

    assert result.result is SchedulerResult.LARAVEL_UNAVAILABLE
    assert executor.state is MissionExecutionState.IDLE


def test_scheduler_returns_idle_when_no_mission_is_due() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    scheduler, executor = build_scheduler(hardware, laravel)

    result = scheduler.tick()

    assert result.result is SchedulerResult.NO_DUE_MISSION
    assert result.robot_datetime == "2026-08-09T21:40:00"
    assert laravel.calls == [(hardware.rtc, "Asia/Hebron")]
    assert executor.state is MissionExecutionState.IDLE


def test_ready_executor_prevents_a_due_mission_claim() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    laravel.claimed_mission = ClaimedMission(9, 1, 2, 1)
    executor = MissionExecutor()
    executor.accept(ClaimedMission(8, 1, 2, 4))
    scheduler, _ = build_scheduler(hardware, laravel, executor)

    result = scheduler.tick()

    assert result.result is SchedulerResult.EXECUTOR_BUSY
    assert result.mission_id == 8
    assert hardware.rtc_calls == 0
    assert laravel.calls == []
    assert executor.mission_id == 8


def test_repeated_ticks_while_executor_is_ready_never_claim_again() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    laravel.claimed_mission = ClaimedMission(9, 1, 2, 1)
    executor = MissionExecutor()
    executor.accept(ClaimedMission(8, 1, 2, 4))
    scheduler, _ = build_scheduler(hardware, laravel, executor)

    results = [scheduler.tick() for _ in range(3)]

    assert all(result.result is SchedulerResult.EXECUTOR_BUSY for result in results)
    assert hardware.rtc_calls == 0
    assert laravel.calls == []


def test_idle_executor_may_claim_a_due_mission() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    laravel.claimed_mission = ClaimedMission(8, 1, 2, 4)
    scheduler, executor = build_scheduler(hardware, laravel)

    result = scheduler.tick()

    assert result.result is SchedulerResult.READY_FOR_EXECUTION
    assert len(laravel.calls) == 1
    assert hardware.rtc_calls == 1
    assert executor.status() == {
        "state": "READY_FOR_EXECUTION",
        "mission_id": 8,
        "room_id": 1,
        "medicine_id": 2,
        "quantity": 4,
    }


def test_due_mission_may_be_claimed_after_executor_returns_to_idle() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    executor = MissionExecutor()
    executor.accept(ClaimedMission(8, 1, 2, 4))
    scheduler, _ = build_scheduler(hardware, laravel, executor)

    busy = scheduler.tick()

    # Mission completion/reset belongs to a later phase. Simulate that future
    # lifecycle transition here without adding a production completion API.
    with executor._lock:
        executor._mission = None
        executor._state = MissionExecutionState.IDLE

    next_mission = ClaimedMission(9, 1, 2, 1)
    laravel.claimed_mission = next_mission
    claimed = scheduler.tick()

    assert busy.result is SchedulerResult.EXECUTOR_BUSY
    assert claimed.result is SchedulerResult.READY_FOR_EXECUTION
    assert laravel.calls == [(hardware.rtc, "Asia/Hebron")]
    assert executor.mission_id == next_mission.id


def test_successful_claim_is_passed_to_executor_exactly_once() -> None:
    class RecordingExecutor(MissionExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.accepted: list[ClaimedMission] = []

        def accept(self, mission: ClaimedMission) -> bool:
            self.accepted.append(mission)
            return super().accept(mission)

    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    mission = ClaimedMission(8, 1, 2, 4)
    laravel.claimed_mission = mission
    executor = RecordingExecutor()
    scheduler, _ = build_scheduler(hardware, laravel, executor)

    first = scheduler.tick()
    second = scheduler.tick()

    assert first.result is SchedulerResult.READY_FOR_EXECUTION
    assert second.result is SchedulerResult.EXECUTOR_BUSY
    assert executor.accepted == [mission]
    assert len(laravel.calls) == 1


def test_failed_acceptance_retries_same_claim_without_calling_laravel_again() -> None:
    class FailOnceExecutor(MissionExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        def accept(self, mission: ClaimedMission) -> bool:
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("injected acceptance failure")
            return super().accept(mission)

    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    mission = ClaimedMission(8, 1, 2, 4)
    laravel.claimed_mission = mission
    executor = FailOnceExecutor()
    scheduler, _ = build_scheduler(hardware, laravel, executor)

    first = scheduler.tick()
    second = scheduler.tick()

    assert first.result is SchedulerResult.EXECUTOR_ACCEPT_FAILED
    assert first.mission_id == mission.id
    assert second.result is SchedulerResult.READY_FOR_EXECUTION
    assert executor.mission_id == mission.id
    assert len(laravel.calls) == 1
    assert hardware.rtc_calls == 1


def test_scheduler_never_calls_movement_or_dispensing() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    laravel.claimed_mission = ClaimedMission(8, 1, 2, 4)
    scheduler, _ = build_scheduler(hardware, laravel)

    scheduler.tick()

    assert hardware.movement_calls == []
    assert hardware.line_calls == []
    assert hardware.camera_calls == []
    assert hardware.dispense_calls == []
    assert hardware.water_calls == []


def test_executor_only_transitions_idle_to_ready() -> None:
    executor = MissionExecutor()
    mission = ClaimedMission(8, 1, 2, 4)

    assert executor.accept(mission) is True
    assert executor.accept(mission) is False
    assert executor.state is MissionExecutionState.READY_FOR_EXECUTION


def test_scheduler_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MISSION_SCHEDULER_ENABLED",
        "MISSION_SCHEDULER_INTERVAL_SECONDS",
        "LARAVEL_API_URL",
        "LARAVEL_API_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = SchedulerSettings.from_environment()

    assert settings.enabled is False
    assert settings.interval_seconds == 5
    assert settings.laravel_api_url == "http://127.0.0.1:8000/api"


def test_disabled_loop_does_not_start_a_thread() -> None:
    hardware = SafeSchedulerHardware()
    laravel = FakeLaravelClient()
    scheduler, _ = build_scheduler(hardware, laravel)
    loop = MissionSchedulerLoop(scheduler, enabled=False, interval_seconds=0.01)

    loop.start()

    assert loop.running is False
    assert hardware.rtc_calls == 0


def test_enabled_loop_starts_only_once_and_stops_cleanly() -> None:
    hardware = SafeSchedulerHardware()
    hardware.available = False
    laravel = FakeLaravelClient()
    scheduler, _ = build_scheduler(hardware, laravel)
    loop = MissionSchedulerLoop(scheduler, enabled=True, interval_seconds=0.01)

    loop.start()
    first_thread = loop._thread
    loop.start()

    assert loop.running is True
    assert loop._thread is first_thread

    loop.stop()

    assert loop.running is False


def test_laravel_client_sends_wall_clock_claim_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/missions/claim-due"
        assert json.loads(request.content) == {
            "robot_datetime": "2026-08-09 21:40:00",
            "timezone": "Asia/Hebron",
        }
        return httpx.Response(
            200,
            json={
                "success": True,
                "claimed": True,
                "mission": {
                    "id": 8,
                    "room": {"id": 1},
                    "medicine": {"id": 2},
                    "quantity": 4,
                },
            },
        )

    client = LaravelApiClient(
        "http://laravel.test/api",
        0.2,
        transport=httpx.MockTransport(handler),
    )

    try:
        mission = client.claim_due_mission(
            datetime(2026, 8, 9, 21, 40, 0),
            "Asia/Hebron",
        )
    finally:
        client.close()

    assert mission == ClaimedMission(8, 1, 2, 4)


def test_laravel_client_maps_timeout_to_clear_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = LaravelApiClient(
        "http://laravel.test/api",
        0.01,
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(LaravelApiUnavailable, match="unavailable"):
            client.claim_due_mission(
                datetime(2026, 8, 9, 21, 40, 0),
                "Asia/Hebron",
            )
    finally:
        client.close()


def test_laravel_client_rejects_invalid_claim_response() -> None:
    client = LaravelApiClient(
        "http://laravel.test/api",
        0.2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"success": True})
        ),
    )

    try:
        with pytest.raises(LaravelApiError, match="mission field"):
            client.claim_due_mission(
                datetime(2026, 8, 9, 21, 40, 0),
                "Asia/Hebron",
            )
    finally:
        client.close()
