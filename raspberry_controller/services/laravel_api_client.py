"""HTTP client for Laravel, the official mission source of truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from .navigation import (
    DirectedConnection,
    PhysicalNavigationMap,
    PhysicalNode,
    PhysicalRoom,
    ReturnRoute,
    RouteDecision,
    RouteStep,
)


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

    def complete_claimed_mission(self, mission: ClaimedMission) -> None:
        """Use Laravel's official arrival endpoint to complete this mission."""

        try:
            response = self._client.post(
                "robot/navigation/arrived",
                json={"mission_id": mission.id},
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise LaravelApiUnavailable(
                "Laravel mission completion API is unavailable"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LaravelApiError(
                "Laravel mission completion failed with HTTP "
                f"{exc.response.status_code}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise LaravelApiError(
                "Laravel mission completion response was not valid JSON"
            ) from exc

        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise LaravelApiError("Laravel mission completion response was invalid")

    def get_navigation_map(self) -> PhysicalNavigationMap:
        """Fetch and validate Laravel's authoritative physical map snapshot."""

        try:
            response = self._client.get("navigation/map")
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise LaravelApiUnavailable("Laravel navigation map is unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise LaravelApiError(
                "Laravel navigation map request failed with HTTP "
                f"{exc.response.status_code}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise LaravelApiError("Laravel navigation map was not valid JSON") from exc

        return _parse_navigation_map(payload)

    def close(self) -> None:
        self._client.close()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LaravelApiError(f"Laravel claim response has an invalid {field}")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LaravelApiError(f"Laravel navigation map has an invalid {field}")
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


def _parse_navigation_map(payload: object) -> PhysicalNavigationMap:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise LaravelApiError("Laravel navigation map has an invalid success field")

    raw_nodes = _list(payload.get("nodes"), "nodes")
    raw_rooms = _list(payload.get("rooms"), "rooms")
    raw_connections = _list(payload.get("connections"), "connections")
    raw_return_routes = _list(
        payload.get("return_routes", []),
        "return_routes",
    )

    nodes: list[PhysicalNode] = []
    node_names: set[str] = set()
    marker_ids: set[int] = set()
    node_ids: set[int] = set()
    for index, raw_node in enumerate(raw_nodes):
        node = _object(raw_node, f"nodes.{index}")
        parsed = PhysicalNode(
            id=_positive_int(node.get("id"), f"nodes.{index}.id"),
            name=_nonempty_string(
                node.get("node_name"),
                f"nodes.{index}.node_name",
            ),
            node_type=_nonempty_string(
                node.get("node_type"),
                f"nodes.{index}.node_type",
            ),
            marker_id=_nonnegative_int(
                node.get("marker_id"),
                f"nodes.{index}.marker_id",
            ),
        )
        if (
            parsed.id in node_ids
            or parsed.name in node_names
            or parsed.marker_id in marker_ids
        ):
            raise LaravelApiError("Laravel navigation map contains duplicate nodes")
        node_ids.add(parsed.id)
        node_names.add(parsed.name)
        marker_ids.add(parsed.marker_id)
        nodes.append(parsed)

    nodes_by_name = {node.name: node for node in nodes}
    rooms: list[PhysicalRoom] = []
    room_ids: set[int] = set()
    for index, raw_room in enumerate(raw_rooms):
        room = _object(raw_room, f"rooms.{index}")
        destination = _object(
            room.get("destination_node"),
            f"rooms.{index}.destination_node",
        )
        destination_node_id = _positive_int(
            destination.get("id"),
            f"rooms.{index}.destination_node.id",
        )
        destination_node_name = _nonempty_string(
            destination.get("node_name"),
            f"rooms.{index}.destination_node.node_name",
        )
        destination_marker_id = _nonnegative_int(
            destination.get("marker_id"),
            f"rooms.{index}.destination_node.marker_id",
        )
        mapped_node = nodes_by_name.get(destination_node_name)
        if (
            mapped_node is None
            or mapped_node.id != destination_node_id
            or mapped_node.marker_id != destination_marker_id
        ):
            raise LaravelApiError(
                "Laravel navigation map contains an inconsistent room destination"
            )

        parsed_room = PhysicalRoom(
            id=_positive_int(room.get("id"), f"rooms.{index}.id"),
            room_number=_nonempty_string(
                room.get("room_number"),
                f"rooms.{index}.room_number",
            ),
            room_name=_nonempty_string(
                room.get("room_name"),
                f"rooms.{index}.room_name",
            ),
            destination_node=destination_node_name,
            destination_marker_id=destination_marker_id,
        )
        if parsed_room.id in room_ids:
            raise LaravelApiError("Laravel navigation map contains duplicate rooms")
        room_ids.add(parsed_room.id)
        rooms.append(parsed_room)

    connections: list[DirectedConnection] = []
    connection_keys: set[tuple[str, str, RouteDecision]] = set()
    for index, raw_connection in enumerate(raw_connections):
        connection = _object(raw_connection, f"connections.{index}")
        from_node = _nonempty_string(
            connection.get("from_node"),
            f"connections.{index}.from_node",
        )
        to_node = _nonempty_string(
            connection.get("to_node"),
            f"connections.{index}.to_node",
        )
        if from_node not in nodes_by_name or to_node not in nodes_by_name:
            raise LaravelApiError(
                "Laravel navigation map connection references an unknown node"
            )
        try:
            direction = RouteDecision(
                _nonempty_string(
                    connection.get("direction"),
                    f"connections.{index}.direction",
                )
            )
        except ValueError as exc:
            raise LaravelApiError(
                "Laravel navigation map contains an unsupported direction"
            ) from exc
        if direction in {
            RouteDecision.U_TURN,
            RouteDecision.ARRIVED,
            RouteDecision.NO_ROUTE,
        }:
            raise LaravelApiError(
                "Laravel navigation map contains a non-traversal direction"
            )

        key = (from_node, to_node, direction)
        if key in connection_keys:
            raise LaravelApiError(
                "Laravel navigation map contains duplicate connections"
            )
        connection_keys.add(key)
        connections.append(
            DirectedConnection(
                from_node=from_node,
                to_node=to_node,
                direction=direction,
            )
        )

    return_routes: list[ReturnRoute] = []
    return_room_ids: set[int] = set()
    for route_index, raw_route in enumerate(raw_return_routes):
        route = _object(raw_route, f"return_routes.{route_index}")
        room_id = _positive_int(
            route.get("room_id"),
            f"return_routes.{route_index}.room_id",
        )
        if room_id not in room_ids or room_id in return_room_ids:
            raise LaravelApiError(
                "Laravel navigation map contains an invalid return route room"
            )
        return_room_ids.add(room_id)
        raw_steps = _list(
            route.get("steps"),
            f"return_routes.{route_index}.steps",
        )
        steps: list[RouteStep] = []
        previous_to_node: str | None = None
        for step_index, raw_step in enumerate(raw_steps):
            step = _object(
                raw_step,
                f"return_routes.{route_index}.steps.{step_index}",
            )
            from_node = _nonempty_string(
                step.get("from_node"),
                f"return_routes.{route_index}.steps.{step_index}.from_node",
            )
            to_node = _nonempty_string(
                step.get("to_node"),
                f"return_routes.{route_index}.steps.{step_index}.to_node",
            )
            if from_node not in nodes_by_name or to_node not in nodes_by_name:
                raise LaravelApiError(
                    "Laravel return route references an unknown node"
                )
            if previous_to_node is not None and previous_to_node != from_node:
                raise LaravelApiError("Laravel return route is not contiguous")
            try:
                direction = RouteDecision(
                    _nonempty_string(
                        step.get("direction"),
                        f"return_routes.{route_index}.steps.{step_index}.direction",
                    )
                )
            except ValueError as exc:
                raise LaravelApiError(
                    "Laravel return route contains an unsupported direction"
                ) from exc
            if direction in {RouteDecision.ARRIVED, RouteDecision.NO_ROUTE}:
                raise LaravelApiError(
                    "Laravel return route contains a non-traversal direction"
                )
            if (step_index == 0) != (direction is RouteDecision.U_TURN):
                raise LaravelApiError(
                    "Laravel return route must begin with exactly one U_TURN"
                )
            steps.append(RouteStep(from_node, direction, to_node))
            previous_to_node = to_node
        if not steps or steps[-1].to_node != "NODE_0":
            raise LaravelApiError("Laravel return route must end at NODE_0")
        return_routes.append(ReturnRoute(room_id, tuple(steps)))

    return PhysicalNavigationMap(
        rooms=tuple(rooms),
        nodes=tuple(nodes),
        connections=tuple(connections),
        return_routes=tuple(return_routes),
    )


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise LaravelApiError(f"Laravel navigation map has an invalid {field}")
    return value
