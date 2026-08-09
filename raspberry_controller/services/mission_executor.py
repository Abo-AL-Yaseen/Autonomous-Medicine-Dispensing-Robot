"""Software-only holder for a claimed mission awaiting future execution."""

from __future__ import annotations

import threading
from enum import Enum

from .laravel_api_client import ClaimedMission


class MissionExecutionState(str, Enum):
    IDLE = "IDLE"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"


class MissionExecutor:
    """Accept one claimed mission without operating any robot hardware."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = MissionExecutionState.IDLE
        self._mission: ClaimedMission | None = None

    @property
    def state(self) -> MissionExecutionState:
        with self._lock:
            return self._state

    @property
    def mission_id(self) -> int | None:
        with self._lock:
            return self._mission.id if self._mission else None

    def accept(self, mission: ClaimedMission) -> bool:
        """Transition IDLE to READY exactly once for the accepted mission."""

        with self._lock:
            if self._state is MissionExecutionState.READY_FOR_EXECUTION:
                if self._mission and self._mission.id == mission.id:
                    return False
                raise RuntimeError("MissionExecutor is already holding a mission")

            self._mission = mission
            self._state = MissionExecutionState.READY_FOR_EXECUTION
            return True

    def status(self) -> dict[str, object]:
        with self._lock:
            mission = self._mission
            return {
                "state": self._state.value,
                "mission_id": mission.id if mission else None,
                "room_id": mission.room_id if mission else None,
                "medicine_id": mission.medicine_id if mission else None,
                "quantity": mission.quantity if mission else None,
            }
