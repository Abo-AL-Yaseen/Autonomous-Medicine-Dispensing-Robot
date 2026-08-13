"""Software-only tests for the first controlled mission execution step."""

from __future__ import annotations

from datetime import datetime

from raspberry_controller.services.laravel_api_client import ClaimedMission
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
        mark_mission_in_progress=dependencies.mark_in_progress,
    )
    assert executor.accept(valid_mission()) is True
    return executor


def navigation_map_for_room_one() -> PhysicalNavigationMap:
    return PhysicalNavigationMap(
        rooms=(PhysicalRoom(1, "1", "Room 1", "ROOM_1", 11),),
        nodes=(
            PhysicalNode(1, "NODE_0", "intersection", 0),
            PhysicalNode(2, "ROOM_1", "room", 11),
        ),
        connections=(
            DirectedConnection("NODE_0", "ROOM_1", RouteDecision.LEFT),
        ),
        return_routes=(
            ReturnRoute(
                1,
                (RouteStep("ROOM_1", RouteDecision.U_TURN, "NODE_0"),),
            ),
        ),
    )


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


def test_invalid_claimed_mission_never_touches_hardware_or_laravel() -> None:
    dependencies = FakeExecutionDependencies()
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        mark_mission_in_progress=dependencies.mark_in_progress,
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
    )
    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()

    assert executor.wait_for_hand_confirmation(1.0).success is True
    assert executor.wait_for_hand_confirmation(1.0).result.value == "HAND_NOT_ALLOWED"
    assert executor.dispense_at_room().success is True
    assert executor.dispense_at_room().result.value == "DISPENSE_NOT_ALLOWED"
    assert dispense_calls == [(1, 4)]


def test_return_home_starts_one_u_turn_and_retains_mission_context() -> None:
    dependencies = FakeExecutionDependencies()
    u_turn_calls: list[str] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: u_turn_calls.append("u_turn") or "ACK|U_TURN_STARTED",
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
    )
    mission = valid_mission()
    assert executor.accept(mission) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()

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
        mark_mission_in_progress=dependencies.mark_in_progress,
        load_navigation_map=navigation_map_for_room_one,
    )

    invalid_state = executor.start_return_home()
    assert invalid_state.result.value == "RETURN_NOT_ALLOWED"

    assert executor.accept(valid_mission()) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()
    dependencies.available = False
    unavailable = executor.start_return_home()

    assert unavailable.result.value == "HARDWARE_UNAVAILABLE"
    assert executor.state is MissionExecutionState.ARRIVED_AT_ROOM
    assert u_turn_calls == []


def test_arrived_home_finalization_completes_and_clears_mission_context() -> None:
    dependencies = FakeExecutionDependencies()
    completed_missions: list[ClaimedMission] = []
    executor = MissionExecutor(
        hardware_available=lambda: dependencies.available,
        start_line_follow=dependencies.start_line_follow,
        stop_line_follow=dependencies.stop_line_follow,
        u_turn=lambda: "ACK|U_TURN_STARTED",
        mark_mission_in_progress=dependencies.mark_in_progress,
        mark_mission_completed=completed_missions.append,
        load_navigation_map=navigation_map_for_room_one,
    )
    mission = valid_mission()
    assert executor.accept(mission) is True
    assert executor.start_ready_mission().success is True
    executor.mark_arrived_at_room()
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
        "last_error": None,
        "auto_execution_enabled": False,
    }
