"""Decision-only navigation engine for the robot map."""

from __future__ import annotations

from collections import deque
from enum import Enum

from .graph import NavigationGraph


class NavigationDecision(str, Enum):
    """Supported move decisions returned by the navigation engine."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"
    STRAIGHT = "STRAIGHT"
    ARRIVED = "ARRIVED"
    UNKNOWN = "UNKNOWN"


class NavigationService:
    """Chooses the next movement for the robot from a current node to a room."""

    def __init__(self, graph: NavigationGraph | None = None) -> None:
        self.graph = graph or NavigationGraph()

    def next_direction(self, current_node_id: int, target_room_id: int) -> str:
        """Return the next movement for the robot based on the current node and target room."""

        target_node_id = self._resolve_target_node_id(target_room_id)
        if target_node_id is None:
            return NavigationDecision.UNKNOWN.value

        if current_node_id == target_node_id:
            return NavigationDecision.ARRIVED.value

        return self._first_direction_on_path(current_node_id, target_node_id)

    def get_next_direction(self, current_node_id: int, target_room_id: int) -> str:
        """Alias method to support a more explicit navigation decision API."""

        return self.next_direction(current_node_id, target_room_id)

    def decide_next_movement(self, current_node_id: int, target_room_id: int) -> str:
        """Compatibility method for callers that describe the action as a movement decision."""

        return self.next_direction(current_node_id, target_room_id)

    def _resolve_target_node_id(self, target_room_id: int) -> int | None:
        """Resolve the room destination marker from the database-backed graph."""

        room = self.graph.get_room(target_room_id)
        if room is None:
            return None
        return room.destination_node_id

    def _first_direction_on_path(self, current_node_id: int, target_node_id: int) -> str:
        """Return the first movement of a shortest directed path, if one exists."""

        visited = {current_node_id}
        pending = deque([(current_node_id, None)])

        while pending:
            node_id, first_direction = pending.popleft()

            for connection in self.graph.get_neighbors(node_id):
                next_node_id = connection.to_node_id
                next_first_direction = first_direction or connection.direction.value

                if next_node_id == target_node_id:
                    return next_first_direction

                if next_node_id not in visited:
                    visited.add(next_node_id)
                    pending.append((next_node_id, next_first_direction))

        return NavigationDecision.UNKNOWN.value
