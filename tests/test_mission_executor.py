"""Software-only tests for the first controlled mission execution step."""

from __future__ import annotations

from datetime import datetime

import pytest

from raspberry_controller.services.laravel_api_client import (
    ClaimedMission,
    ClaimedMissionItem,
)
from raspberry_controller.services.mission_executor import (
    MissionExecutionState,
    MissionExecutor,
    MissionStartResult,
)
from raspberry_controller.services.navigation import (
    DirectedConnection,
    PhysicalNavigationMap,
    PhysicalNode,
    PhysicalRoom,
    ReturnRoute,
    RouteDecision,
    RouteStep,
)
from raspberry_controller.services.mission_scheduler import (
    MissionScheduler,
    SchedulerResult,
)


class FakeExecutionDependencies:
    def __init__(self) -> None:
        self.available = True
        self.start_ack = "ACK|LINE_FOLLOW_STARTED"
        self.stop_ack = "ACK|LINE_FOLLOW_STOPPED"
        self.start_error: Exception | None = None
        self.update_error: Exception | None = None
        self.line_calls: list[str] = []
        self.updated_missions: list[ClaimedMission] = []
        self.motor_calls: list[str] = []
        self.camera_calls: list[str] = []
        self.dispense_calls: list[object] = []
        self.water_calls: list[object] = []
        self.water_level_calls = 0
        self.water_level_status = "OK"
        self.water_level_error: Exception | None = None
        self.return_home_calls: list[str] = []

    def start_line_follow(self) -> str:
        self.line_calls.append("start")
        if self.start_error:
            raise self.start_error
        return self.start_ack

    def stop_line_follow(self) -> str:
        self.line_calls.append("stop")
        return self.stop_ack

    def mark_in_progress(self, mission: ClaimedMission) -> None:
        self.updated_missions.append(mission)
        if self.update_error:
            raise self.update_error

    def get_water_level(self) -> dict[str, object]:
        self.water_level_calls += 1
        if self.water_level_error is not None:
            raise self.water_level_error
        return {"status": self.water_level_status}


class ClaimTrackingLaravelClient:
    def __init__(self) -> None:
        self.claim_calls: list[tuple[datetime, str]] = []

    def claim_due_mission(
        self,
        robot_datetime: datetime,
        timezone_name: str,
    ) -> ClaimedMission | None:
        self.claim_calls.append((robot_datetime, timezone_name))
        return valid_mission(9)

    def start_claimed_mission(self, mission: ClaimedMission) -> None:
        raise AssertionError("Scheduler must not start execution")

    def close(self) -> None:
        pass


def valid_mission(mission_id: int = 8) -> ClaimedMission:
    return ClaimedMission(
        mission_id,
        1,
        2,
        4,
        room_number="204",
        dispenser_box=1,
        schedule_claimed_at="2026-08-09T18:40:00+00:00",
    )


def ready_executor(
    dependencies: FakeExecutionDependencies,
) -> MissionExecutor:
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        get_water_level=dependencies.get_water_level,
        mark_mission_in_progress=dependencies.mark_in_progress,
        require_home_readiness=False,
    )
    assert executor.accept(valid_mission()) is True
    return executor


def navigation_map_for_room_one() -> PhysicalNavigationMap:
    return PhysicalNavigationMap(
        rooms=(PhysicalRoom(1, "1", "Room 1", "ROOM_1", 11),),
        nodes=(
            PhysicalNode(1, "NODE_0", "intersection", 0),
            PhysicalNode(2, "ROOM_1", "room", 11),
            PhysicalNode(3, "HOME", "home", 10),
        ),
        connections=(
            DirectedConnection("HOME", "NODE_0", RouteDecision.STRAIGHT),
            DirectedConnection("NODE_0", "HOME", RouteDecision.STRAIGHT),
            DirectedConnection("NODE_0", "ROOM_1", RouteDecision.LEFT),
        ),
        return_routes=(
            ReturnRoute(
                1,
                (
                    RouteStep("ROOM_1", RouteDecision.U_TURN, "NODE_0"),
                    RouteStep("NODE_0", RouteDecision.RIGHT, "HOME"),
                ),
            ),
        ),
    )


def successful_dispense(box: int, quantity: int) -> dict[str, int]:
    return {
        "box_number": box,
        "requested_pills": quantity,
        "dispensed_pills": quantity,
    }


def complete_delivery_pickup(executor: MissionExecutor) -> None:
    """Advance a room-arrived executor through the guarded zero countdown tick."""

    assert executor.wait_for_hand_confirmation(1.0).success
    assert executor.dispense_at_room().success
    assert executor.dispense_water_at_room().success
    assert executor.begin_pickup_wait()
    assert executor.update_pickup_wait(0)
    assert executor.complete_pickup_wait()


def medicine_completed_executor(
    *,
    dispense_water,
    get_water_level=None,
    u_turn=lambda: "ACK|U_TURN_STARTED",
) -> MissionExecutor:
    dependencies = FakeExecutionDependencies()
    start_preflight_pending = True

    def mission_water_level() -> dict[str, object]:
        if start_preflight_pending:
            return {"status": "OK"}
        assert get_water_level is not None
        return get_water_level()

    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=u_turn,
        wait_for_hand=lambda _: True,
        dispense_medicine=successful_dispense,
        dispense_water=dispense_water,
        get_water_level=(mission_water_level if get_water_level is not None else None),
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    assert executor.accept(valid_mission())
    assert executor.start_ready_mission().success
    start_preflight_pending = False
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1.0).success
    assert executor.dispense_at_room().success
    return executor


def test_accept_resolves_destination_from_laravel_map_without_hardware() -> None:
    dependencies = FakeExecutionDependencies()
    map_calls: list[str] = []

    def load_map() -> PhysicalNavigationMap:
        map_calls.append("load")
        return navigation_map_for_room_one()

    executor = MissionExecutor(load_navigation_map=load_map)

    assert executor.accept(valid_mission()) is True
    mission, plan = executor.plan_route(0)

    assert mission.id == 8
    assert executor.destination_node == PhysicalNode(2, "ROOM_1", "room", 11)
    assert executor.marker_for_node("ROOM_1") == 11
    assert plan.decision is RouteDecision.LEFT
    assert plan.next_node == "ROOM_1"
    assert map_calls == ["load"]
    assert dependencies.line_calls == []
    assert dependencies.motor_calls == []


def test_map_resolution_failure_leaves_executor_idle_for_safe_retry() -> None:
    def fail_to_load_map() -> PhysicalNavigationMap:
        raise RuntimeError("Laravel unavailable")

    executor = MissionExecutor(load_navigation_map=fail_to_load_map)

    try:
        executor.accept(valid_mission())
    except RuntimeError as exc:
        assert str(exc) == "Laravel unavailable"
    else:
        raise AssertionError("map loading failure must reject mission acceptance")

    assert executor.state is MissionExecutionState.IDLE
    assert executor.mission_id is None


def test_hardware_unavailable_does_not_start_or_update_laravel() -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.available = False
    executor = ready_executor(dependencies)

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.HARDWARE_UNAVAILABLE
    assert executor.state is MissionExecutionState.READY_FOR_EXECUTION
    assert dependencies.line_calls == []
    assert dependencies.updated_missions == []


@pytest.mark.parametrize(
    ("water_status", "expected_result"),
    [
        ("EMPTY", MissionStartResult.WATER_EMPTY),
        ("SENSOR_ERROR", MissionStartResult.WATER_LEVEL_SENSOR_ERROR),
    ],
)
def test_water_preflight_rejects_before_any_autonomous_movement(
    water_status: str,
    expected_result: MissionStartResult,
) -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.water_level_status = water_status
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=dependencies.start_line_follow,
        u_turn=lambda: u_turn_calls.append("u-turn") or "ACK|U_TURN_STARTED",
        get_water_level=dependencies.get_water_level,
        mark_mission_in_progress=dependencies.mark_in_progress,
    )
    assert executor.accept(valid_mission()) is True
    executor.set_home_readiness(True)

    result = executor.start_ready_mission()

    assert result.result is expected_result
    assert result.success is False
    assert executor.state is MissionExecutionState.READY_FOR_EXECUTION
    assert executor.mission_id == valid_mission().id
    assert dependencies.water_level_calls == 1
    assert u_turn_calls == []
    assert dependencies.line_calls == []
    assert dependencies.updated_missions == []


def test_water_preflight_sensor_request_failure_is_retryable() -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.water_level_error = RuntimeError("ultrasonic timeout")
    executor = ready_executor(dependencies)

    rejected = executor.start_ready_mission()
    dependencies.water_level_error = None
    retried = executor.start_ready_mission()

    assert rejected.result is MissionStartResult.WATER_LEVEL_SENSOR_ERROR
    assert retried.result is MissionStartResult.STARTED
    assert dependencies.water_level_calls == 2
    assert dependencies.line_calls == ["start"]
    assert dependencies.updated_missions == [valid_mission()]


@pytest.mark.parametrize("water_status", ["OK", "LOW"])
def test_water_preflight_allows_ok_and_low(water_status: str) -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.water_level_status = water_status
    executor = ready_executor(dependencies)

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.STARTED
    assert dependencies.water_level_calls == 1
    assert dependencies.line_calls == ["start"]
    assert dependencies.updated_missions == [valid_mission()]


def test_invalid_claimed_mission_never_touches_hardware_or_laravel() -> None:
    dependencies = FakeExecutionDependencies()
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        mark_mission_in_progress=dependencies.mark_in_progress,
        require_home_readiness=False,
    )
    executor.accept(ClaimedMission(8, 1, 2, 4))

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.INVALID_MISSION
    assert executor.state is MissionExecutionState.FAILED
    assert dependencies.line_calls == []
    assert dependencies.updated_missions == []


def test_success_starts_line_follow_and_updates_laravel_once() -> None:
    dependencies = FakeExecutionDependencies()
    executor = ready_executor(dependencies)

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.STARTED
    assert dependencies.line_calls == ["start"]
    assert dependencies.updated_missions == [valid_mission()]
    assert executor.state is MissionExecutionState.GOING_TO_ROOM


def test_home_readiness_blocks_start_then_u_turn_precedes_line_follow() -> None:
    dependencies = FakeExecutionDependencies()
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u-turn") or "ACK|U_TURN_STARTED",
        mark_mission_in_progress=dependencies.mark_in_progress,
    )
    assert executor.accept(valid_mission()) is True

    blocked = executor.start_ready_mission()

    assert blocked.result is MissionStartResult.HOME_NOT_CONFIRMED
    assert executor.state is MissionExecutionState.READY_FOR_EXECUTION
    assert u_turn_calls == []
    assert dependencies.line_calls == []

    executor.set_home_readiness(True)
    started = executor.start_ready_mission()

    assert started.result is MissionStartResult.U_TURN_STARTED
    assert executor.state is MissionExecutionState.STARTING
    assert u_turn_calls == ["u-turn"]
    assert dependencies.line_calls == []

    completed = executor.complete_start_u_turn()

    assert completed.result is MissionStartResult.STARTED
    assert executor.state is MissionExecutionState.GOING_TO_ROOM
    assert dependencies.line_calls == ["start"]


def test_line_follow_failure_leaves_laravel_pending() -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.start_error = RuntimeError("serial timeout")
    executor = ready_executor(dependencies)

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.LINE_FOLLOW_START_FAILED
    assert dependencies.line_calls == ["start", "stop"]
    assert dependencies.updated_missions == []
    assert executor.state is MissionExecutionState.FAILED


def test_malformed_line_follow_ack_does_not_update_laravel() -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.start_ack = "ACK|WRONG"
    executor = ready_executor(dependencies)

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.LINE_FOLLOW_START_FAILED
    assert dependencies.updated_missions == []
    assert dependencies.line_calls == ["start", "stop"]
    assert executor.state is MissionExecutionState.FAILED


def test_laravel_failure_stops_line_follow_immediately() -> None:
    dependencies = FakeExecutionDependencies()
    dependencies.update_error = RuntimeError("Laravel unavailable")
    executor = ready_executor(dependencies)

    result = executor.start_ready_mission()

    assert result.result is MissionStartResult.MISSION_STATUS_UPDATE_FAILED
    assert dependencies.line_calls == ["start", "stop"]
    assert len(dependencies.updated_missions) == 1
    assert executor.state is MissionExecutionState.FAILED


def test_repeated_start_does_not_issue_duplicate_line_command() -> None:
    dependencies = FakeExecutionDependencies()
    executor = ready_executor(dependencies)

    first = executor.start_ready_mission()
    second = executor.start_ready_mission()

    assert first.result is MissionStartResult.STARTED
    assert second.result is MissionStartResult.EXECUTOR_BUSY
    assert dependencies.line_calls == ["start"]
    assert len(dependencies.updated_missions) == 1


def test_going_to_room_blocks_scheduler_claims() -> None:
    dependencies = FakeExecutionDependencies()
    executor = ready_executor(dependencies)
    assert executor.start_ready_mission().success is True
    laravel = ClaimTrackingLaravelClient()
    rtc_calls: list[datetime] = []

    def read_rtc() -> datetime:
        value = datetime(2026, 8, 9, 21, 40, 0)
        rtc_calls.append(value)
        return value

    scheduler = MissionScheduler(
        hardware_available=lambda: True,
        read_rtc=read_rtc,
        laravel_client=laravel,
        executor=executor,
        timezone_name="Asia/Hebron",
    )

    result = scheduler.tick()

    assert result.result is SchedulerResult.EXECUTOR_BUSY
    assert rtc_calls == []
    assert laravel.claim_calls == []


def test_execution_step_calls_no_out_of_scope_hardware() -> None:
    dependencies = FakeExecutionDependencies()
    executor = ready_executor(dependencies)

    executor.start_ready_mission()

    assert dependencies.motor_calls == []
    assert dependencies.camera_calls == []
    assert dependencies.dispense_calls == []
    assert dependencies.water_calls == []
    assert dependencies.return_home_calls == []


def test_partial_sensor_confirmed_dispense_fails_and_cannot_start_return_home() -> None:
    dependencies = FakeExecutionDependencies()
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
        wait_for_hand=lambda timeout: True,
        dispense_medicine=lambda box, quantity: {
            "box_number": box,
            "requested_pills": quantity,
            "dispensed_pills": quantity - 1,
        },
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1.0).success is True

    dispense = executor.dispense_at_room()
    returned = executor.start_return_home()

    assert dispense.success is False
    assert dispense.result.value == "DISPENSE_FAILED"
    assert executor.state is MissionExecutionState.FAILED
    assert returned.result.value == "RETURN_NOT_ALLOWED"
    assert u_turn_calls == []


def test_arrival_waits_for_hand_and_blocks_dispense_until_confirmation() -> None:
    dependencies = FakeExecutionDependencies()
    hand_checks: list[float] = []
    dispense_calls: list[tuple[int, int]] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        wait_for_hand=lambda timeout: hand_checks.append(timeout) or True,
        dispense_medicine=lambda box, quantity: (
            dispense_calls.append((box, quantity))
            or {
                "box_number": box,
                "requested_pills": quantity,
                "dispensed_pills": quantity,
            }
        ),
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()

    assert executor.dispense_at_room().result.value == "DISPENSE_NOT_ALLOWED"
    assert dispense_calls == []

    hand = executor.wait_for_hand_confirmation(12.0)
    assert hand.success is True
    assert executor.state is MissionExecutionState.WAITING_FOR_HAND

    assert executor.dispense_at_room().success is True
    assert hand_checks == [12.0]
    assert dispense_calls == [(1, 4)]


def test_hand_timeout_fails_without_uno_dispense_or_return_home() -> None:
    dependencies = FakeExecutionDependencies()
    u_turn_calls: list[str] = []
    dispense_calls: list[tuple[int, int]] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
        wait_for_hand=lambda timeout: False,
        dispense_medicine=lambda box, quantity: dispense_calls.append((box, quantity)) or {},
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()

    hand = executor.wait_for_hand_confirmation(1.0)

    assert hand.result.value == "HAND_TIMEOUT"
    assert executor.state is MissionExecutionState.FAILED
    assert executor.status()["last_error"] == "HAND_TIMEOUT"
    assert executor.dispense_at_room().result.value == "DISPENSE_NOT_ALLOWED"
    assert executor.start_return_home().result.value == "RETURN_NOT_ALLOWED"
    assert dispense_calls == []
    assert u_turn_calls == []


def test_duplicate_hand_confirmation_cannot_start_a_second_dispense() -> None:
    dependencies = FakeExecutionDependencies()
    dispense_calls: list[tuple[int, int]] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        wait_for_hand=lambda timeout: True,
        dispense_medicine=lambda box, quantity: (
            dispense_calls.append((box, quantity))
            or {
                "box_number": box,
                "requested_pills": quantity,
                "dispensed_pills": quantity,
            }
        ),
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()

    assert executor.wait_for_hand_confirmation(1.0).success is True
    assert executor.wait_for_hand_confirmation(1.0).result.value == "HAND_NOT_ALLOWED"
    assert executor.dispense_at_room().success is True
    assert executor.dispense_at_room().result.value == "DISPENSE_NOT_ALLOWED"
    assert dispense_calls == [(1, 4)]


def test_multi_medicine_mission_dispenses_each_laravel_item_in_order() -> None:
    dependencies = FakeExecutionDependencies()
    calls: list[tuple[int, int]] = []
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: "ACK|U_TURN_STARTED",
        wait_for_hand=lambda _: True,
        dispense_medicine=lambda box, quantity: calls.append((box, quantity)) or {
            "box_number": box,
            "requested_pills": quantity,
            "dispensed_pills": quantity,
        },
        dispense_water=lambda duration: {"duration_ms": duration},
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    mission = ClaimedMission(
        88, 1, 99, 2, room_number="204", dispenser_box=1,
        schedule_claimed_at="2026-08-09T18:40:00+00:00",
        mission_items=(
            ClaimedMissionItem(99, 2, 1),
            ClaimedMissionItem(42, 1, 2),
        ),
    )
    executor.accept(mission)
    assert executor.start_ready_mission().success
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1).success

    assert executor.dispense_at_room().success
    assert calls == [(1, 2), (2, 1)]
    assert executor.dispense_water_at_room().success
    assert executor.begin_pickup_wait()
    assert executor.update_pickup_wait(0)
    assert executor.complete_pickup_wait()
    assert executor.start_return_home().success


def test_multi_medicine_failure_stops_before_later_item_and_return() -> None:
    dependencies = FakeExecutionDependencies()
    calls: list[tuple[int, int]] = []
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
        wait_for_hand=lambda _: True,
        dispense_medicine=lambda box, quantity: calls.append((box, quantity)) or {
            "box_number": box,
            "requested_pills": quantity,
            "dispensed_pills": 0,
        },
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    mission = ClaimedMission(
        89, 1, 99, 2, room_number="204", dispenser_box=1,
        schedule_claimed_at="2026-08-09T18:40:00+00:00",
        mission_items=(ClaimedMissionItem(99, 2, 1), ClaimedMissionItem(42, 1, 2)),
    )
    executor.accept(mission)
    assert executor.start_ready_mission().success
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1).success

    failed = executor.dispense_at_room()
    assert failed.success is False
    assert calls == [(1, 2)]
    assert "medicine_id=99 box=1 requested=2 confirmed=0" in (failed.message or "")
    assert executor.start_return_home().success is False
    assert u_turn_calls == []


def test_uncalibrated_required_disk_fails_before_any_multi_item_dispense() -> None:
    dependencies = FakeExecutionDependencies()
    calls: list[tuple[int, int]] = []
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        wait_for_hand=lambda _: True,
        get_disk_status=lambda: {
            "disk1": {"calibrated": True, "slot": 0},
            "disk2": {"calibrated": False, "slot": 0},
        },
        dispense_medicine=lambda box, quantity: calls.append((box, quantity)) or {
            "box_number": box,
            "requested_pills": quantity,
            "dispensed_pills": quantity,
        },
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    mission = ClaimedMission(
        90, 1, 99, 2, room_number="204", dispenser_box=1,
        schedule_claimed_at="2026-08-09T18:40:00+00:00",
        mission_items=(ClaimedMissionItem(99, 2, 1), ClaimedMissionItem(42, 1, 2)),
    )
    executor.accept(mission)
    assert executor.start_ready_mission().success
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1).success

    result = executor.dispense_at_room()

    assert result.success is False
    assert calls == []
    assert result.message == "DISPENSE_FAILED: DISK_NOT_CALIBRATED|BOX=2"
    assert executor.start_return_home().success is False


def test_calibrated_disks_allow_normal_multi_item_dispense() -> None:
    dependencies = FakeExecutionDependencies()
    calls: list[tuple[int, int]] = []
    executor = MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        wait_for_hand=lambda _: True,
        get_disk_status=lambda: {
            "disk1": {"calibrated": True, "slot": 0},
            "disk2": {"calibrated": True, "slot": 0},
        },
        dispense_medicine=lambda box, quantity: calls.append((box, quantity)) or {
            "box_number": box,
            "requested_pills": quantity,
            "dispensed_pills": quantity,
        },
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    mission = ClaimedMission(
        91, 1, 99, 2, room_number="204", dispenser_box=1,
        schedule_claimed_at="2026-08-09T18:40:00+00:00",
        mission_items=(ClaimedMissionItem(99, 2, 1), ClaimedMissionItem(42, 1, 2)),
    )
    executor.accept(mission)
    assert executor.start_ready_mission().success
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1).success

    assert executor.dispense_at_room().success
    assert calls == [(1, 2), (2, 1)]


def test_mission_water_is_exactly_4500_ms_and_runs_only_once_after_medicine() -> None:
    water_calls: list[int] = []
    executor = medicine_completed_executor(
        dispense_water=lambda duration: water_calls.append(duration) or {
            "duration_ms": duration
        },
        get_water_level=lambda: {"status": "OK"},
    )

    first = executor.dispense_water_at_room()
    duplicate = executor.dispense_water_at_room()

    assert first.success is True
    assert duplicate.success is False
    assert water_calls == [4500]
    assert executor.state is MissionExecutionState.WATER_DISPENSE_COMPLETED


def test_water_failure_preserves_error_and_prevents_pickup_countdown() -> None:
    def fail_water(duration: int) -> dict[str, int]:
        raise RuntimeError("PUMP_TIMEOUT")

    executor = medicine_completed_executor(dispense_water=fail_water)

    result = executor.dispense_water_at_room()

    assert result.success is False
    assert executor.state is MissionExecutionState.FAILED
    assert executor.status()["last_error"] == "WATER_DISPENSE_FAILED: PUMP_TIMEOUT"
    assert executor.begin_pickup_wait() is False
    assert executor.start_return_home().success is False


def test_empty_water_level_prevents_pump_and_pickup_wait() -> None:
    water_calls: list[int] = []
    executor = medicine_completed_executor(
        dispense_water=lambda duration: water_calls.append(duration) or {
            "duration_ms": duration
        },
        get_water_level=lambda: {"status": "EMPTY"},
    )

    result = executor.dispense_water_at_room()

    assert result.success is False
    assert water_calls == []
    assert executor.status()["last_error"] == "WATER_DISPENSE_FAILED: WATER_EMPTY"
    assert executor.begin_pickup_wait() is False


def test_pickup_status_starts_at_30_and_return_requires_zero_tick() -> None:
    u_turn_calls: list[str] = []
    executor = medicine_completed_executor(
        dispense_water=lambda duration: {"duration_ms": duration},
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
    )
    assert executor.dispense_water_at_room().success

    assert executor.begin_pickup_wait() is True
    assert executor.status()["state"] == "WAITING_FOR_PICKUP"
    assert executor.status()["pickup_seconds_remaining"] == 30
    assert executor.start_return_home().success is False
    assert executor.update_pickup_wait(1)
    assert executor.start_return_home().success is False
    assert executor.update_pickup_wait(0)
    assert executor.complete_pickup_wait()
    assert executor.start_return_home().success is True
    assert u_turn_calls == ["u_turn"]


def test_return_home_starts_one_u_turn_and_retains_mission_context() -> None:
    dependencies = FakeExecutionDependencies()
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
        wait_for_hand=lambda _: True,
        dispense_medicine=successful_dispense,
        dispense_water=lambda duration: {"duration_ms": duration},
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    mission = valid_mission()
    assert executor.accept(mission) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()
    complete_delivery_pickup(executor)

    first = executor.start_return_home()
    second = executor.start_return_home()

    assert first.success is True
    assert first.result.value == "RETURN_STARTED"
    assert second.success is False
    assert second.result.value == "RETURN_NOT_ALLOWED"
    assert u_turn_calls == ["u_turn"]
    assert executor.state is MissionExecutionState.RETURNING_HOME
    assert executor.mission_id == mission.id
    assert dependencies.updated_missions == [mission]
    assert dependencies.dispense_calls == []
    assert dependencies.water_calls == []


def test_return_home_invalid_state_and_hardware_failure_do_not_turn() -> None:
    dependencies = FakeExecutionDependencies()
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
        wait_for_hand=lambda _: True,
        dispense_medicine=successful_dispense,
        dispense_water=lambda duration: {"duration_ms": duration},
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )

    invalid_state = executor.start_return_home()
    assert invalid_state.result.value == "RETURN_NOT_ALLOWED"

    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()
    complete_delivery_pickup(executor)
    dependencies.available = False
    unavailable = executor.start_return_home()

    assert unavailable.result.value == "HARDWARE_UNAVAILABLE"
    assert executor.state is MissionExecutionState.WAITING_FOR_PICKUP
    assert u_turn_calls == []


def test_arrived_home_finalization_completes_and_clears_mission_context() -> None:
    dependencies = FakeExecutionDependencies()
    completed_missions: list[ClaimedMission] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: "ACK|U_TURN_STARTED",
        wait_for_hand=lambda _: True,
        dispense_medicine=successful_dispense,
        dispense_water=lambda duration: {"duration_ms": duration},
        mark_mission_in_progress=dependencies.mark_in_progress,
        mark_mission_completed=completed_missions.append,
        load_navigation_map=navigation_map_for_room_one,
        require_home_readiness=False,
    )
    mission = valid_mission()
    assert executor.accept(mission) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()
    complete_delivery_pickup(executor)
    assert executor.start_return_home().success is True
    executor.mark_arrived_home()

    assert executor.state is MissionExecutionState.ARRIVED_HOME
    assert executor.finalize_arrived_home() is True
    assert completed_missions == [mission]
    assert executor.status() == {
        "state": "IDLE",
        "mission_id": None,
        "room_id": None,
        "room_number": None,
        "target_room": None,
        "medicine_id": None,
        "dispenser_box": None,
        "quantity": None,
        "pickup_seconds_remaining": None,
        "last_error": None,
        "auto_execution_enabled": False,
        "home_ready": True,
        "home_readiness_error": None,
    }
