"""Hardware-free tests for the optional voice playback queue."""

from __future__ import annotations

import threading
import time

from raspberry_controller.services.voice_service import (
    ARABIC_MESSAGES,
    VoiceEvent,
    VoiceService,
    VoiceSettings,
)


class RecordingPlayer:
    def __init__(self) -> None:
        self.events: list[VoiceEvent] = []
        self.messages: list[str] = []
        self.closed = False
        self.played = threading.Event()

    def play(self, event: VoiceEvent, message: str) -> None:
        self.events.append(event)
        self.messages.append(message)
        self.played.set()

    def close(self) -> None:
        self.closed = True


class BlockingPlayer(RecordingPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def play(self, event: VoiceEvent, message: str) -> None:
        super().play(event, message)
        self.release.wait(5.0)

    def close(self) -> None:
        super().close()
        self.release.set()


class FirstPlaybackFails(RecordingPlayer):
    def play(self, event: VoiceEvent, message: str) -> None:
        super().play(event, message)
        if len(self.events) == 1:
            raise RuntimeError("speaker unavailable")


def enabled_settings() -> VoiceSettings:
    return VoiceSettings(enabled=True)


def wait_for_count(player: RecordingPlayer, count: int) -> None:
    deadline = time.monotonic() + 1.0
    while len(player.events) < count and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(player.events) == count


def test_voice_settings_default_disabled_and_accept_explicit_opt_in(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_LANGUAGE", raising=False)
    monkeypatch.delenv("VOICE_AUDIO_DIR", raising=False)
    monkeypatch.delenv("VOICE_PLAYBACK_TIMEOUT_SECONDS", raising=False)

    defaults = VoiceSettings.from_environment()
    assert defaults.enabled is False
    assert defaults.language == "ar"
    assert defaults.audio_directory is None

    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOICE_LANGUAGE", "ar")
    monkeypatch.setenv("VOICE_AUDIO_DIR", str(tmp_path))
    monkeypatch.setenv("VOICE_PLAYBACK_TIMEOUT_SECONDS", "12")

    configured = VoiceSettings.from_environment()
    assert configured.enabled is True
    assert configured.audio_directory == tmp_path
    assert configured.playback_timeout_seconds == 12.0


def test_events_are_played_in_queue_order_and_duplicates_are_ignored() -> None:
    player = RecordingPlayer()
    voice = VoiceService(enabled_settings(), player=player)
    voice.start()

    assert voice.say(VoiceEvent.ARRIVED_AT_ROOM, scope=17) is True
    assert voice.say(VoiceEvent.ARRIVED_AT_ROOM, scope=17) is False
    assert voice.say(VoiceEvent.WAITING_FOR_HAND, scope=17) is True
    wait_for_count(player, 2)
    voice.close()

    assert player.events == [
        VoiceEvent.ARRIVED_AT_ROOM,
        VoiceEvent.WAITING_FOR_HAND,
    ]
    assert player.messages == [
        ARABIC_MESSAGES[VoiceEvent.ARRIVED_AT_ROOM],
        ARABIC_MESSAGES[VoiceEvent.WAITING_FOR_HAND],
    ]


def test_say_does_not_wait_for_speech_completion() -> None:
    player = BlockingPlayer()
    voice = VoiceService(enabled_settings(), player=player)
    voice.start()

    started = time.monotonic()
    assert voice.say(VoiceEvent.RETURNING_HOME, scope=18) is True
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert player.played.wait(1.0)
    voice.close()
    assert player.closed is True
    assert voice.status()["worker_running"] is False


def test_playback_failure_does_not_stop_later_queue_items(caplog) -> None:
    player = FirstPlaybackFails()
    voice = VoiceService(enabled_settings(), player=player)
    voice.start()

    voice.say(VoiceEvent.DISPENSING, scope=19)
    voice.say(VoiceEvent.MEDICINE_COMPLETED, scope=19)
    wait_for_count(player, 2)
    voice.close()

    assert player.events == [
        VoiceEvent.DISPENSING,
        VoiceEvent.MEDICINE_COMPLETED,
    ]
    assert "VOICE playback failed: speaker unavailable" in caplog.text


def test_disabled_mode_has_no_worker_or_playback() -> None:
    player = RecordingPlayer()
    voice = VoiceService(VoiceSettings(enabled=False), player=player)

    voice.start()
    assert voice.say(VoiceEvent.MISSION_STARTED, scope=20) is False
    assert voice.status()["worker_running"] is False
    voice.close()

    assert player.events == []
    assert player.closed is True


def test_arabic_patient_messages_are_exact() -> None:
    assert ARABIC_MESSAGES[VoiceEvent.MISSION_STARTED] == (
        "تم بدء مهمة توصيل الدواء."
    )
    assert ARABIC_MESSAGES[VoiceEvent.ARRIVED_AT_ROOM] == (
        "تم الوصول إلى الغرفة المطلوبة."
    )
    assert ARABIC_MESSAGES[VoiceEvent.WAITING_FOR_HAND] == (
        "يرجى وضع كوب الماء في المكان المخصص، ثم وضع يدك عند مخرج الدواء."
    )
    assert ARABIC_MESSAGES[VoiceEvent.HAND_DETECTED] == (
        "تم التأكيد، يرجى إبقاء الكوب واليد في مكانهما."
    )
    assert ARABIC_MESSAGES[VoiceEvent.DELIVERY_COMPLETED] == (
        "تم تسليم الدواء والماء بنجاح. نتمنى لكم السلامة."
    )
