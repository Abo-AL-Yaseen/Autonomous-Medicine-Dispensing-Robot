"""Navigation graph service for the hospital map.

This module is the only place that reads the SQLite graph data for nodes,
rooms, and connections. The rest of the application should interact with the
NavigationGraph service instead of importing SQLAlchemy models directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from ..database import Connection, Node, Room, SessionLocal
NodeLike = int | Node
RoomLike = int | Room


class NavigationGraph:
    """Read-only service that exposes the hospital graph from SQLite."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def load_graph(self) -> dict[str, list[object]]:
        """Load the complete graph snapshot from the database."""

        return {
            "nodes": self.load_nodes(),
            "connections": self.load_connections(),
            "rooms": self.load_rooms(),
        }

    def load_nodes(self) -> list[Node]:
        """Return every node in the hospital graph."""

        with self._session_factory() as session:
            return list(session.query(Node).order_by(Node.id).all())

    def load_connections(self) -> list[Connection]:
        """Return every directed connection in the hospital graph."""

        with self._session_factory() as session:
            return list(session.query(Connection).order_by(Connection.id).all())

    def load_rooms(self) -> list[Room]:
        """Return every room definition persisted in the database."""

        with self._session_factory() as session:
            return list(session.query(Room).order_by(Room.id).all())

    def get_node(self, node_id: int) -> Node | None:
        """Fetch a node by its primary key."""

        with self._session_factory() as session:
            return session.get(Node, node_id)

    def get_room(self, room_id: int) -> Room | None:
        """Fetch a room by its primary key."""

        with self._session_factory() as session:
            return session.get(Room, room_id)

    def get_neighbors(self, node_id: int) -> list[Connection]:
        """Return all outgoing connections from a node."""

        with self._session_factory() as session:
            return list(
                session.query(Connection)
                .filter(Connection.from_node_id == node_id)
                .order_by(Connection.id)
                .all()
            )

    def get_connection(self, from_node: NodeLike, to_node: NodeLike) -> Connection | None:
        """Fetch a directed connection between two nodes."""

        from_id = self._resolve_node_id(from_node)
        to_id = self._resolve_node_id(to_node)

        with self._session_factory() as session:
            return (
                session.query(Connection)
                .filter(Connection.from_node_id == from_id, Connection.to_node_id == to_id)
                .first()
            )

    def room_destination(self, room_id: int) -> Node | None:
        """Return the destination node configured for a room, if it exists."""

        room = self.get_room(room_id)
        if room is None:
            return None
        return room.destination_node

    @staticmethod
    def _resolve_node_id(node: NodeLike) -> int:
        """Resolve either an integer ID or a node instance to a numeric ID."""

        if isinstance(node, Node):
            return node.id
        return node
