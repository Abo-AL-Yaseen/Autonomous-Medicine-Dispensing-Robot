"""Directed route planning over Laravel's read-only physical map snapshot."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum


class RouteDecision(str, Enum):
    U_TURN = "U_TURN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    STRAIGHT = "STRAIGHT"
    ARRIVED = "ARRIVED"
    NO_ROUTE = "NO_ROUTE"


class NavigationMapError(RuntimeError):
    """Laravel navigation map data is missing or internally inconsistent."""


class UnknownMarkerError(NavigationMapError):
    """The supplied marker does not exist in Laravel's physical map."""


@dataclass(frozen=True)
class PhysicalNode:
    id: int
    name: str
    node_type: str
    marker_id: int


@dataclass(frozen=True)
class PhysicalRoom:
    id: int
    room_number: str
    room_name: str
    destination_node: str
    destination_marker_id: int


@dataclass(frozen=True)
class DirectedConnection:
    from_node: str
    to_node: str
    direction: RouteDecision


@dataclass(frozen=True)
class ReturnRoute:
    room_id: int
    steps: tuple["RouteStep", ...]


@dataclass(frozen=True)
class PhysicalNavigationMap:
    rooms: tuple[PhysicalRoom, ...]
    nodes: tuple[PhysicalNode, ...]
    connections: tuple[DirectedConnection, ...]
    return_routes: tuple[ReturnRoute, ...] = ()

    def node_for_marker(self, marker_id: int) -> PhysicalNode | None:
        return next(
            (node for node in self.nodes if node.marker_id == marker_id),
            None,
        )

    def node_named(self, node_name: str) -> PhysicalNode | None:
        return next((node for node in self.nodes if node.name == node_name), None)

    def room_by_id(self, room_id: int) -> PhysicalRoom | None:
        return next((room for room in self.rooms if room.id == room_id), None)

    def return_route_for_room(self, room_id: int) -> ReturnRoute | None:
        return next(
            (route for route in self.return_routes if route.room_id == room_id),
            None,
        )


@dataclass(frozen=True)
class RouteStep:
    from_node: str
    direction: RouteDecision
    to_node: str

    def as_dict(self) -> dict[str, str]:
        return {
            "from_node": self.from_node,
            "direction": self.direction.value,
            "to_node": self.to_node,
        }


@dataclass(frozen=True)
class RoutePlan:
    current_node: PhysicalNode
    destination_node: PhysicalNode
    decision: RouteDecision
    next_node: str | None
    steps: tuple[RouteStep, ...]

    @property
    def success(self) -> bool:
        return self.decision is not RouteDecision.NO_ROUTE


class LaravelRoutePlanner:
    """Compute shortest directed routes without invoking robot hardware."""

    def __init__(self, navigation_map: PhysicalNavigationMap) -> None:
        self.navigation_map = navigation_map

    def plan(self, current_marker_id: int, destination_room_id: int) -> RoutePlan:
        current_node = self.navigation_map.node_for_marker(current_marker_id)
        if current_node is None:
            raise UnknownMarkerError(
                f"Marker {current_marker_id} is not present in Laravel's map"
            )

        room = self.navigation_map.room_by_id(destination_room_id)
        if room is None:
            raise NavigationMapError(
                f"Room {destination_room_id} is not present in Laravel's map"
            )

        destination_node = self.navigation_map.node_named(room.destination_node)
        if destination_node is None:
            raise NavigationMapError(
                f"Room {destination_room_id} has an unknown destination node"
            )
        if destination_node.marker_id != room.destination_marker_id:
            raise NavigationMapError(
                f"Room {destination_room_id} destination marker is inconsistent"
            )

        if current_node.name == destination_node.name:
            return RoutePlan(
                current_node=current_node,
                destination_node=destination_node,
                decision=RouteDecision.ARRIVED,
                next_node=None,
                steps=(),
            )

        steps = self._shortest_path(current_node.name, destination_node.name)
        if not steps:
            return RoutePlan(
                current_node=current_node,
                destination_node=destination_node,
                decision=RouteDecision.NO_ROUTE,
                next_node=None,
                steps=(),
            )

        return RoutePlan(
            current_node=current_node,
            destination_node=destination_node,
            decision=steps[0].direction,
            next_node=steps[0].to_node,
            steps=steps,
        )

    def destination_for_room(self, room_id: int) -> PhysicalNode:
        room = self.navigation_map.room_by_id(room_id)
        if room is None:
            raise NavigationMapError(f"Room {room_id} is not present in Laravel's map")
        node = self.navigation_map.node_named(room.destination_node)
        if node is None or node.marker_id != room.destination_marker_id:
            raise NavigationMapError(
                f"Room {room_id} has an invalid destination mapping"
            )
        return node

    def plan_return(self, current_marker_id: int, room_id: int) -> RoutePlan:
        current_node = self.navigation_map.node_for_marker(current_marker_id)
        if current_node is None:
            raise UnknownMarkerError(
                f"Marker {current_marker_id} is not present in Laravel's map"
            )

        home_node = self.navigation_map.node_named("HOME")
        if home_node is None or home_node.node_type != "home":
            raise NavigationMapError("Laravel's map has no dedicated HOME node")

        if current_node.name == home_node.name:
            return RoutePlan(
                current_node=current_node,
                destination_node=home_node,
                decision=RouteDecision.ARRIVED,
                next_node=None,
                steps=(),
            )

        route = self.navigation_map.return_route_for_room(room_id)
        if route is None:
            return RoutePlan(
                current_node=current_node,
                destination_node=home_node,
                decision=RouteDecision.NO_ROUTE,
                next_node=None,
                steps=(),
            )

        try:
            index = next(
                index
                for index, step in enumerate(route.steps)
                if step.from_node == current_node.name
            )
        except StopIteration:
            return RoutePlan(
                current_node=current_node,
                destination_node=home_node,
                decision=RouteDecision.NO_ROUTE,
                next_node=None,
                steps=(),
            )

        steps = route.steps[index:]
        step = steps[0]
        return RoutePlan(
            current_node=current_node,
            destination_node=home_node,
            decision=step.direction,
            next_node=step.to_node,
            steps=steps,
        )

    def _shortest_path(
        self,
        current_node: str,
        destination_node: str,
    ) -> tuple[RouteStep, ...]:
        adjacency: dict[str, list[DirectedConnection]] = {}
        for connection in self.navigation_map.connections:
            adjacency.setdefault(connection.from_node, []).append(connection)

        pending: deque[tuple[str, tuple[RouteStep, ...]]] = deque(
            [(current_node, ())]
        )
        visited = {current_node}

        while pending:
            node_name, path = pending.popleft()
            for connection in adjacency.get(node_name, []):
                if connection.to_node in visited:
                    continue

                next_path = path + (
                    RouteStep(
                        from_node=connection.from_node,
                        direction=connection.direction,
                        to_node=connection.to_node,
                    ),
                )
                if connection.to_node == destination_node:
                    return next_path

                visited.add(connection.to_node)
                pending.append((connection.to_node, next_path))

        return ()
