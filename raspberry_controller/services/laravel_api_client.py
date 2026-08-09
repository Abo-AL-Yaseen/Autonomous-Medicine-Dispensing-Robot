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

        return ClaimedMission(
            id=_positive_int(mission.get("id"), "mission.id"),
            room_id=_nested_id(mission.get("room"), "mission.room"),
            medicine_id=_nested_id(mission.get("medicine"), "mission.medicine"),
            quantity=_positive_int(mission.get("quantity"), "mission.quantity"),
        )

    def close(self) -> None:
        self._client.close()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LaravelApiError(f"Laravel claim response has an invalid {field}")
    return value


def _nested_id(value: object, field: str) -> int:
    if not isinstance(value, dict):
        raise LaravelApiError(f"Laravel claim response has an invalid {field}")
    return _positive_int(value.get("id"), f"{field}.id")
