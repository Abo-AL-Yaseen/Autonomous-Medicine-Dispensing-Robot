"""Non-blocking Arabic voice guidance through the Linux default audio output."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


logger = logging.getLogger(__name__)

DEFAULT_VOICE_LANGUAGE = "ar"
DEFAULT_PLAYBACK_TIMEOUT_SECONDS = 30.0
MAX_DEDUPLICATION_KEYS = 512


class VoiceEvent(str, Enum):
    """Patient-facing events; navigation and serial debug events do not belong here."""

    MISSION_STARTED = "MISSION_STARTED"
    ARRIVED_AT_ROOM = "ARRIVED_AT_ROOM"
    WAITING_FOR_HAND = "WAITING_FOR_HAND"
    HAND_DETECTED = "HAND_DETECTED"
    DISPENSING = "DISPENSING"
    MEDICINE_COMPLETED = "MEDICINE_COMPLETED"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    RETURNING_HOME = "RETURNING_HOME"
    ARRIVED_HOME = "ARRIVED_HOME"
    MANUAL_RECOVERY = "MANUAL_RECOVERY"
    MEDICINE_FAILED = "MEDICINE_FAILED"
    WATER_FAILED = "WATER_FAILED"
    GENERAL_FAILED = "GENERAL_FAILED"
    TEST = "TEST"


ARABIC_MESSAGES: dict[VoiceEvent, str] = {
    VoiceEvent.MISSION_STARTED: "تم بدء مهمة توصيل الدواء.",
    VoiceEvent.ARRIVED_AT_ROOM: "تم الوصول إلى الغرفة المطلوبة.",
    VoiceEvent.WAITING_FOR_HAND: (
        "يرجى وضع كوب الماء في المكان المخصص، ثم وضع يدك عند مخرج الدواء."
    ),
    VoiceEvent.HAND_DETECTED: (
        "تم التأكيد، يرجى إبقاء الكوب واليد في مكانهما."
    ),
    VoiceEvent.DISPENSING: "جاري صرف الدواء، يرجى الانتظار.",
    VoiceEvent.MEDICINE_COMPLETED: (
        "تم صرف الدواء بنجاح، جاري تعبئة الماء."
    ),
    VoiceEvent.DELIVERY_COMPLETED: (
        "تم تسليم الدواء والماء بنجاح. نتمنى لكم السلامة."
    ),
    VoiceEvent.RETURNING_HOME: "جاري العودة إلى نقطة البداية.",
    VoiceEvent.ARRIVED_HOME: "تم الوصول إلى نقطة البداية.",
    VoiceEvent.MANUAL_RECOVERY: (
        "تم فقدان المسار، يرجى إعادة الروبوت إلى الخط ثم الضغط على متابعة."
    ),
    VoiceEvent.MEDICINE_FAILED: (
        "تنبيه، تعذر صرف الدواء. يرجى طلب المساعدة."
    ),
    VoiceEvent.WATER_FAILED: (
        "تنبيه، يتعذر توفير الماء حالياً. يرجى طلب المساعدة."
    ),
    VoiceEvent.GENERAL_FAILED: (
        "حدث خطأ في النظام. يرجى طلب المساعدة."
    ),
    VoiceEvent.TEST: "مرحباً، نظام الصوت يعمل بنجاح.",
}


@dataclass(frozen=True)
class VoiceSettings:
    """Minimal opt-in voice configuration loaded once during API startup."""

    enabled: bool = False
    language: str = DEFAULT_VOICE_LANGUAGE
    audio_directory: Path | None = None
    playback_timeout_seconds: float = DEFAULT_PLAYBACK_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> "VoiceSettings":
        audio_directory = os.getenv("VOICE_AUDIO_DIR")
        timeout_raw = os.getenv("VOICE_PLAYBACK_TIMEOUT_SECONDS")
        timeout = DEFAULT_PLAYBACK_TIMEOUT_SECONDS
        if timeout_raw is not None:
            try:
                timeout = float(timeout_raw)
            except ValueError as exc:
                raise ValueError(
                    "VOICE_PLAYBACK_TIMEOUT_SECONDS must be a number"
                ) from exc
            if timeout <= 0:
                raise ValueError(
                    "VOICE_PLAYBACK_TIMEOUT_SECONDS must be positive"
                )

        return cls(
            enabled=_read_boolean_setting("VOICE_ENABLED", False),
            language=os.getenv("VOICE_LANGUAGE", DEFAULT_VOICE_LANGUAGE),
            audio_directory=(
                Path(audio_directory).expanduser()
                if audio_directory
                else None
            ),
            playback_timeout_seconds=timeout,
        )


class VoiceAnnouncer(Protocol):
    """Small dependency boundary consumed by the mission executor."""

    def say(self, event: VoiceEvent, *, scope: int | str | None = None) -> bool:
        """Queue an event and return immediately."""


class AudioPlayer(Protocol):
    """Blocking player interface used only inside the voice worker."""

    def play(self, event: VoiceEvent, message: str) -> None:
        """Play one message to completion."""

    def close(self) -> None:
        """Interrupt and release any active playback resources."""


class LinuxAudioPlayer:
    """Offline eSpeak NG synthesis with optional prerecorded WAV overrides.

    ``paplay`` targets the current PulseAudio/PipeWire default sink. Commands
    are always passed as argument lists; message text is never interpreted by
    a shell.
    """

    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[bytes] | None = None
        self._closed = False

    def play(self, event: VoiceEvent, message: str) -> None:
        prerecorded = self._prerecorded_path(event)
        if prerecorded is not None:
            self._run_process(["paplay", str(prerecorded)])
            return

        wav_data = self._run_process(
            [
                "espeak-ng",
                "--stdout",
                "-v",
                self._settings.language,
                message,
            ],
            capture_output=True,
        )
        self._run_process(["paplay"], input_data=wav_data)

    def close(self) -> None:
        with self._process_lock:
            self._closed = True
            process = self._active_process
        if process is not None and process.poll() is None:
            process.terminate()

    def _prerecorded_path(self, event: VoiceEvent) -> Path | None:
        directory = self._settings.audio_directory
        if directory is None:
            return None
        candidate = directory / f"{event.value.lower()}.wav"
        return candidate if candidate.is_file() else None

    def _run_process(
        self,
        command: list[str],
        *,
        input_data: bytes | None = None,
        capture_output: bool = False,
    ) -> bytes:
        with self._process_lock:
            if self._closed:
                raise RuntimeError("audio player is closed")
            process = subprocess.Popen(
                command,
                stdin=(
                    subprocess.PIPE
                    if input_data is not None
                    else subprocess.DEVNULL
                ),
                stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._active_process = process
        try:
            try:
                stdout, stderr = process.communicate(
                    input=input_data,
                    timeout=self._settings.playback_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise RuntimeError(
                    f"{command[0]} exceeded the playback timeout"
                ) from exc
        finally:
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None

        if process.returncode != 0:
            error_text = (stderr or b"").decode("utf-8", errors="replace").strip()
            detail = f": {error_text[:200]}" if error_text else ""
            raise RuntimeError(f"{command[0]} exited with {process.returncode}{detail}")
        return stdout or b""


@dataclass(frozen=True)
class _QueuedSpeech:
    event: VoiceEvent
    message: str


class VoiceService:
    """Queue patient guidance without making mission execution wait for audio."""

    def __init__(
        self,
        settings: VoiceSettings,
        *,
        player: AudioPlayer | None = None,
    ) -> None:
        self._settings = settings
        self._player = player or LinuxAudioPlayer(settings)
        self._queue: queue.Queue[_QueuedSpeech | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._seen_keys: dict[tuple[str, VoiceEvent], None] = {}
        self._closed = False
        self._worker: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def start(self) -> None:
        """Start the single playback worker; disabled mode remains inert."""

        with self._state_lock:
            if not self.enabled or self._closed or self._worker is not None:
                return
            self._worker = threading.Thread(
                target=self._run,
                name="voice-playback",
                daemon=True,
            )
            try:
                self._worker.start()
            except Exception as exc:
                self._worker = None
                logger.warning("VOICE worker start failed: %s", exc)

    def say(self, event: VoiceEvent, *, scope: int | str | None = None) -> bool:
        """Queue one deduplicated event without waiting for synthesis or playback."""

        with self._state_lock:
            if not self.enabled or self._closed:
                return False
            deduplication_key = (str(scope) if scope is not None else "global", event)
            if deduplication_key in self._seen_keys:
                return False
            self._seen_keys[deduplication_key] = None
            if len(self._seen_keys) > MAX_DEDUPLICATION_KEYS:
                oldest_key = next(iter(self._seen_keys))
                del self._seen_keys[oldest_key]

        self._queue.put(_QueuedSpeech(event, ARABIC_MESSAGES[event]))
        logger.info("VOICE event=%s", event.value)
        return True

    def status(self) -> dict[str, object]:
        with self._state_lock:
            worker = self._worker
            return {
                "enabled": self.enabled,
                "language": self._settings.language,
                "worker_running": bool(worker and worker.is_alive()),
                "queued_messages": self._queue.qsize(),
                "prerecorded_audio_directory": (
                    str(self._settings.audio_directory)
                    if self._settings.audio_directory is not None
                    else None
                ),
            }

    def close(self, timeout_seconds: float = 2.0) -> None:
        """Stop playback promptly without hanging application shutdown."""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            worker = self._worker
        self._stop_event.set()
        try:
            self._player.close()
        except Exception as exc:
            logger.warning("VOICE shutdown failed: %s", exc)
        self._queue.put(None)
        if worker is not None:
            worker.join(timeout=max(0.0, timeout_seconds))

    def _run(self) -> None:
        while True:
            speech = self._queue.get()
            try:
                if speech is None or self._stop_event.is_set():
                    return
                try:
                    self._player.play(speech.event, speech.message)
                except Exception as exc:
                    if not self._stop_event.is_set():
                        logger.warning("VOICE playback failed: %s", exc)
            finally:
                self._queue.task_done()


def _read_boolean_setting(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")
