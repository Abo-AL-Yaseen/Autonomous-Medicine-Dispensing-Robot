"""HTTP client for Laravel, the official mission source of truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx


class LaravelApiError(RuntimeError):
    """Laravel returned an invalid or unsuccessful response."""


class LaravelApiUnavailable(LaravelApiError):
    """Laravel could not be reached within the configured timeout."""


@dataclass(frozen=True)
class ClaimedMission:
    """Minimum Laravel mission data needed by the runtime executor."""

    id: int
    room_id: int
    medicine_id: int
    quantity: int
    room_number: str | None = None
    dispenser_box: int | None = None
    schedule_claimed_at: str | None = None


class LaravelApiClient:
    """Call Laravel over HTTP without reading its database directly."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def claim_due_mission(
        self,
        robot_datetime: datetime,
        timezone_name: str,
    ) -> ClaimedMission | None:
        """Claim at most one due Laravel mission for a DS1302 wall-clock."""

        if robot_datetime.tzinfo is not None:
            raise ValueError("robot_datetime must be a timezone-naive wall-clock")

        try:
            response = self._client.post(
                "missions/claim-due",
                json={
                    "robot_datetime": robot_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    "timezone": timezone_name,
                },
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise LaravelApiUnavailable("Laravel mission API is unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise LaravelApiError(
                f"Laravel claim request failed with HTTP {exc.response.status_code}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise LaravelApiError("Laravel claim response was not valid JSON") from exc

        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise LaravelApiError("Laravel claim response has an invalid success field")

        claimed = payload.get("claimed")
        mission = payload.get("mission")
        if claimed is False and mission is None:
            return None
        if claimed is not True or not isinstance(mission, dict):
            raise LaravelApiError("Laravel claim response has an invalid mission field")

        room = _object(mission.get("room"), "mission.room")
        medicine = _object(mission.get("medicine"), "mission.medicine")

        return ClaimedMission(
            id=_positive_int(mission.get("id"), "mission.id"),
            room_id=_positive_int(room.get("id"), "mission.room.id"),
            medicine_id=_positive_int(
                medicine.get("id"),
                "mission.medicine.id",
            ),
            quantity=_positive_int(mission.get("quantity"), "mission.quantity"),
            room_number=_optional_nonempty_string(
                room.get("room_number"),
                "mission.room.room_number",
            ),
            dispenser_box=_optional_dispenser_box(
                medicine.get("dispenser_box")
            ),
            schedule_claimed_at=_nonempty_string(
                mission.get("schedule_claimed_at"),
                "mission.schedule_claimed_at",
            ),
        )

    def start_claimed_mission(self, mission: ClaimedMission) -> None:
        """Atomically transition this exact Laravel claim to in_progress."""

        if not mission.schedule_claimed_at:
            raise LaravelApiError("Claimed mission has no schedule_claimed_at")

        try:
            response = self._client.post(
                f"missions/{mission.id}/start-execution",
                json={"schedule_claimed_at": mission.schedule_claimed_at},
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise LaravelApiUnavailable("Laravel mission API is unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise LaravelApiError(
                "Laravel mission start failed with HTTP "
                f"{exc.response.status_code}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise LaravelApiError("Laravel mission start response was not valid JSON") from exc

        started_mission = payload.get("mission") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or not isinstance(started_mission, dict)
            or started_mission.get("id") != mission.id
            or started_mission.get("status") != "in_progress"
        ):
            raise LaravelApiError("Laravel mission start response was invalid")

    def close(self) -> None:
        self._client.close()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LaravelApiError(f"Laravel claim response has an invalid {field}")
    return value


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LaravelApiError(f"Laravel claim response has an invalid {field}")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LaravelApiError(f"Laravel claim response has an invalid {field}")
    return value


def _optional_nonempty_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field)


def _optional_dispenser_box(value: object) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in (1, 2)
    ):
        raise LaravelApiError(
            "Laravel claim response has an invalid mission.medicine.dispenser_box"
        )
    return value
