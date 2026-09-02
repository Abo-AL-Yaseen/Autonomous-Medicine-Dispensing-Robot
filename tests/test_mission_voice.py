"""Voice event integration tests at real MissionExecutor transitions."""

from __future__ import annotations

import threading

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

    def say_and_wait(
        self,
        event: VoiceEvent,
        *,
        scope: int | str | None = None,
        timeout: float | None = None,
    ) -> bool:
        return self.say(event, scope=scope)


class GatedVoice(RecordingVoice):
    def __init__(self, gated_event: VoiceEvent, *, fail: bool = False) -> None:
        super().__init__(fail=fail)
        self.gated_event = gated_event
        self.playback_started = threading.Event()
        self.playback_release = threading.Event()

    def say_and_wait(
        self,
        event: VoiceEvent,
        *,
        scope: int | str | None = None,
        timeout: float | None = None,
    ) -> bool:
        result = self.say(event, scope=scope)
        if event is self.gated_event:
            self.playback_started.set()
            self.playback_release.wait(1.0)
        return result


class TimeoutVoice(RecordingVoice):
    def say_and_wait(
        self,
        event: VoiceEvent,
        *,
        scope: int | str | None = None,
        timeout: float | None = None,
    ) -> bool:
        self.events.append((event, scope))
        return False


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
                    RouteStep("NODE_0", RouteDecision.RIGHT, "HOME"),
                ),
            ),
        ),
    )


def build_executor(
    voice: RecordingVoice,
    *,
    wait_for_hand=None,
    u_turn=None,
    dispense_medicine=None,
    dispense_water=None,
) -> MissionExecutor:
    return MissionExecutor(
        hardware_available=lambda: True,
        start_line_follow=lambda: "ACK|LINE_FOLLOW_STARTED",
        stop_line_follow=lambda: "ACK|LINE_FOLLOW_STOPPED",
        u_turn=u_turn or (lambda: "ACK|U_TURN_STARTED"),
        wait_for_hand=wait_for_hand or (lambda _timeout: True),
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


def test_voice_timeout_result_never_fails_physical_mission_stages() -> None:
    voice = TimeoutVoice()
    executor = build_executor(voice)

    advance_to_hand_confirmed(executor)
    assert executor.dispense_at_room().success
    assert executor.dispense_water_at_room().success
    assert executor.begin_pickup_wait(1)
    assert executor.update_pickup_wait(0)
    assert executor.start_return_home().success

    assert executor.state is MissionExecutionState.RETURNING_HOME


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


def test_manual_recovery_voice_failure_does_not_block_recovery(caplog) -> None:
    voice = RecordingVoice(fail=True)
    executor = build_executor(voice)
    assert executor.accept(mission())
    assert executor.start_ready_mission().success

    snapshot = executor.begin_manual_recovery("LINE_LOST")

    assert snapshot is not None
    assert executor.state is MissionExecutionState.WAITING_FOR_MANUAL_RECOVERY
    assert VoiceEvent.MANUAL_RECOVERY in event_names(voice)
    assert "VOICE enqueue failed: voice queue unavailable" in caplog.text


def test_hand_polling_starts_only_after_waiting_prompt_completes() -> None:
    voice = GatedVoice(VoiceEvent.WAITING_FOR_HAND)
    hand_polled = threading.Event()
    executor = build_executor(
        voice,
        wait_for_hand=lambda _timeout: hand_polled.set() or True,
    )
    assert executor.accept(mission())
    assert executor.start_ready_mission().success
    executor.mark_arrived_at_room()
    outcomes = []
    caller = threading.Thread(
        target=lambda: outcomes.append(executor.wait_for_hand_confirmation(1.0))
    )

    caller.start()
    assert voice.playback_started.wait(1.0)
    assert hand_polled.is_set() is False
    voice.playback_release.set()
    caller.join(1.0)

    assert outcomes[0].success is True
    assert hand_polled.is_set()


def test_medicine_command_waits_for_dispensing_prompt() -> None:
    voice = GatedVoice(VoiceEvent.DISPENSING)
    medicine_sent = threading.Event()
    executor = build_executor(
        voice,
        dispense_medicine=lambda box, quantity: (
            medicine_sent.set()
            or {
                "box_number": box,
                "requested_pills": quantity,
                "dispensed_pills": quantity,
            }
        ),
    )
    advance_to_hand_confirmed(executor)
    outcomes = []
    caller = threading.Thread(
        target=lambda: outcomes.append(executor.dispense_at_room())
    )

    caller.start()
    assert voice.playback_started.wait(1.0)
    assert medicine_sent.is_set() is False
    voice.playback_release.set()
    caller.join(1.0)

    assert outcomes[0].success is True
    assert medicine_sent.is_set()


def test_water_command_waits_for_medicine_completed_prompt() -> None:
    voice = GatedVoice(VoiceEvent.MEDICINE_COMPLETED)
    water_sent = threading.Event()
    executor = build_executor(
        voice,
        dispense_water=lambda duration: water_sent.set() or {"duration_ms": duration},
    )
    advance_to_hand_confirmed(executor)
    medicine_outcomes = []
    caller = threading.Thread(
        target=lambda: medicine_outcomes.append(executor.dispense_at_room())
    )

    caller.start()
    assert voice.playback_started.wait(1.0)
    assert executor.state is MissionExecutionState.DISPENSING
    assert water_sent.is_set() is False
    voice.playback_release.set()
    caller.join(1.0)
    assert medicine_outcomes[0].success is True

    assert executor.dispense_water_at_room().success
    assert water_sent.is_set()


def test_return_u_turn_waits_for_returning_home_prompt() -> None:
    voice = GatedVoice(VoiceEvent.RETURNING_HOME)
    u_turn_sent = threading.Event()
    executor = build_executor(
        voice,
        u_turn=lambda: u_turn_sent.set() or "ACK|U_TURN_STARTED",
    )
    advance_to_hand_confirmed(executor)
    assert executor.dispense_at_room().success
    assert executor.dispense_water_at_room().success
    assert executor.begin_pickup_wait(1)
    assert executor.update_pickup_wait(0)
    outcomes = []
    caller = threading.Thread(
        target=lambda: outcomes.append(executor.start_return_home())
    )

    caller.start()
    assert voice.playback_started.wait(1.0)
    assert executor.state is MissionExecutionState.RETURNING_HOME
    assert u_turn_sent.is_set() is False
    voice.playback_release.set()
    caller.join(1.0)

    assert outcomes[0].success is True
    assert u_turn_sent.is_set()


def test_arrived_home_voice_failure_does_not_prevent_cleanup(caplog) -> None:
    voice = RecordingVoice(fail=True)
    executor = build_executor(voice)
    advance_to_hand_confirmed(executor)
    assert executor.dispense_at_room().success
    assert executor.dispense_water_at_room().success
    assert executor.begin_pickup_wait(1)
    assert executor.update_pickup_wait(0)
    assert executor.start_return_home().success

    executor.mark_arrived_home()
    assert executor.finalize_arrived_home() is True

    assert executor.state is MissionExecutionState.IDLE
    assert executor.mission_id is None
    assert "VOICE blocking playback failed" in caplog.text
