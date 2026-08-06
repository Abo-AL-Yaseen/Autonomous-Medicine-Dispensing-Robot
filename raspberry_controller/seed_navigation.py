"""Seed the hospital navigation map used by the Raspberry Pi controller."""

from __future__ import annotations

from .database import Connection, Direction, Node, Room, SessionLocal


NODES = {
    0: ("NODE_0", "Decision marker 0"),
    1: ("NODE_1", "Decision marker 1"),
    2: ("NODE_2", "Decision marker 2"),
    11: ("ROOM_MARKER_11", "Room 1 marker"),
    12: ("ROOM_MARKER_12", "Room 2 marker"),
    13: ("ROOM_MARKER_13", "Room 3 marker"),
    14: ("ROOM_MARKER_14", "Room 4 marker"),
    15: ("ROOM_MARKER_15", "Room 5 marker"),
}

ROOMS = {
    1: ("1", "Room 1", 11),
    2: ("2", "Room 2", 12),
    3: ("3", "Room 3", 13),
    4: ("4", "Room 4", 14),
    5: ("5", "Room 5", 15),
}

CONNECTIONS = (
    (0, 11, Direction.LEFT),
    (0, 1, Direction.STRAIGHT),
    (1, 2, Direction.LEFT),
    (1, 14, Direction.RIGHT),
    (1, 15, Direction.STRAIGHT),
    (2, 13, Direction.LEFT),
    (2, 12, Direction.RIGHT),
)


def seed_navigation() -> None:
    """Insert the navigation map once, without duplicating existing records."""

    inserted_nodes = 0
    inserted_rooms = 0
    inserted_connections = 0

    with SessionLocal() as session:
        for node_id, (node_code, description) in NODES.items():
            if session.get(Node, node_id) is None:
                session.add(Node(id=node_id, node_code=node_code, description=description))
                inserted_nodes += 1

        for room_id, (room_number, room_name, destination_node_id) in ROOMS.items():
            if session.get(Room, room_id) is None:
                session.add(
                    Room(
                        id=room_id,
                        room_number=room_number,
                        room_name=room_name,
                        destination_node_id=destination_node_id,
                    )
                )
                inserted_rooms += 1

        for from_node_id, to_node_id, direction in CONNECTIONS:
            connection_exists = (
                session.query(Connection)
                .filter(
                    Connection.from_node_id == from_node_id,
                    Connection.to_node_id == to_node_id,
                    Connection.direction == direction,
                )
                .first()
            )
            if connection_exists is None:
                session.add(
                    Connection(
                        from_node_id=from_node_id,
                        to_node_id=to_node_id,
                        direction=direction,
                    )
                )
                inserted_connections += 1

        session.commit()

    print(f"Nodes inserted: {inserted_nodes}")
    print(f"Rooms inserted: {inserted_rooms}")
    print(f"Connections inserted: {inserted_connections}")


if __name__ == "__main__":
    seed_navigation()
