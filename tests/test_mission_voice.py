"""Voice event integration tests at real MissionExecutor transitions."""

from __future__ import annotations

from raspberry_controller.services.laravel_api_client import ClaimedMission
from raspberry_controller.services.mission_executor import (
    MissionExecutionState,
    MissionExecutor,
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
from raspberry_controller.services.voice_service import VoiceEvent


class RecordingVoice:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[tuple[VoiceEvent, int | str | None]] = []
        self.fail = fail

    def say(self, event: VoiceEvent, *, scope: int | str | None = None) -> bool:
        self.events.append((event, scope))
        if self.fail:
            raise RuntimeError("voice queue unavailable")
        return True


def mission() -> ClaimedMission:
    return ClaimedMission(
        41,
        1,
        2,
        1,
        room_number="204",
        dispenser_box=1,
        schedule_claimed_at="2026-08-26T10:00:00+00:00",
    )


def navigation_map() -> PhysicalNavigationMap:
    return PhysicalNavigationMap(
        rooms=(PhysicalRoom(1, "204", "Room 204", "ROOM_1", 11),),
        nodes=(
            PhysicalNode(1, "HOME", "home", 10),
            PhysicalNode(2, "NODE_0", "intersection", 0),
            PhysicalNode(3, "ROOM_1", "room", 11),
        ),
        connections=(
            DirectedConnection("HOME", "NODE_0", RouteDecision.STRAIGHT),
            DirectedConnection("NODE_0", "ROOM_1", RouteDecision.LEFT),
        ),
        return_routes=(
            ReturnRoute(
                1,
                (
                    RouteStep("ROOM_1", RouteDecision.U_TURN, "NODE_0"),
                    RouteStep("NODE_0", RouteDecision.STRAIGHT, "HOME"),
                ),
            ),
        ),
    )


def build_executor(
    voice: RecordingVoice,
    *,
    dispense_medicine=None,
    dispense_water=None,
) -> MissionExecutor:
    return MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=lambda: "ACK|LINE_FOLLOW_STARTED",
        stop_line_follow=lambda: "ACK|LINE_FOLLOW_STOPPED",
        u_turn=lambda: "ACK|U_TURN_STARTED",
        wait_for_hand=lambda _timeout: True,
        dispense_medicine=dispense_medicine
        or (
            lambda box, quantity: {
                "box_number": box,
                "requested_pills": quantity,
                "dispensed_pills": quantity,
            }
        ),
        dispense_water=dispense_water
        or (lambda duration: {"duration_ms": duration}),
        get_water_level=lambda: {"status": "OK"},
        mark_mission_in_progress=lambda _mission: None,
        mark_mission_completed=lambda _mission: None,
        load_navigation_map=navigation_map,
        voice=voice,
        require_home_readiness=False,
    )


def event_names(voice: RecordingVoice) -> list[VoiceEvent]:
    return [event for event, _scope in voice.events]


def advance_to_hand_confirmed(executor: MissionExecutor) -> None:
    assert executor.accept(mission())
    assert executor.start_ready_mission().success
    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1.0).success


def test_successful_mission_announces_only_patient_facing_transitions() -> None:
    voice = RecordingVoice()
    executor = build_executor(voice)

    assert executor.accept(mission())
    assert executor.start_ready_mission().success

    before_navigation = list(voice.events)
    executor.plan_route(10)
    executor.marker_for_node("NODE_0")
    assert voice.events == before_navigation

    executor.mark_arrived_at_room()
    assert executor.wait_for_hand_confirmation(1.0).success
    assert executor.dispense_at_room().success
    assert executor.dispense_water_at_room().success
    assert executor.begin_pickup_wait(1)
    assert executor.update_pickup_wait(0)
    assert executor.complete_pickup_wait()
    assert executor.start_return_home().success
    executor.mark_arrived_home()

    assert event_names(voice) == [
        VoiceEvent.MISSION_STARTED,
        VoiceEvent.ARRIVED_AT_ROOM,
        VoiceEvent.WAITING_FOR_HAND,
        VoiceEvent.HAND_DETECTED,
        VoiceEvent.DISPENSING,
        VoiceEvent.MEDICINE_COMPLETED,
        VoiceEvent.DELIVERY_COMPLETED,
        VoiceEvent.RETURNING_HOME,
        VoiceEvent.ARRIVED_HOME,
    ]
    assert {scope for _event, scope in voice.events} == {41}


def test_voice_enqueue_failure_never_changes_successful_mission_state(caplog) -> None:
    voice = RecordingVoice(fail=True)
    executor = build_executor(voice)

    advance_to_hand_confirmed(executor)
    assert executor.dispense_at_room().success
    assert executor.dispense_water_at_room().success

    assert executor.state is MissionExecutionState.WATER_DISPENSE_COMPLETED
    assert "VOICE enqueue failed: voice queue unavailable" in caplog.text


def test_medicine_failure_has_one_specific_failure_event() -> None:
    voice = RecordingVoice()

    def fail_dispense(_box: int, _quantity: int) -> dict[str, int]:
        raise RuntimeError("PILL_TIMEOUT")

    executor = build_executor(voice, dispense_medicine=fail_dispense)
    advance_to_hand_confirmed(executor)

    assert executor.dispense_at_room().success is False
    assert event_names(voice).count(VoiceEvent.MEDICINE_FAILED) == 1
    assert VoiceEvent.WATER_FAILED not in event_names(voice)
    assert VoiceEvent.GENERAL_FAILED not in event_names(voice)


def test_water_failure_has_one_specific_failure_event() -> None:
    voice = RecordingVoice()

    def fail_water(_duration: int) -> dict[str, int]:
        raise RuntimeError("PUMP_TIMEOUT")

    executor = build_executor(voice, dispense_water=fail_water)
    advance_to_hand_confirmed(executor)
    assert executor.dispense_at_room().success

    assert executor.dispense_water_at_room().success is False
    assert event_names(voice).count(VoiceEvent.WATER_FAILED) == 1
    assert VoiceEvent.DELIVERY_COMPLETED not in event_names(voice)
    assert VoiceEvent.GENERAL_FAILED not in event_names(voice)
