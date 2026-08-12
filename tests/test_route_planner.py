"""Tests for Laravel-backed, decision-only physical route planning."""

from __future__ import annotations

import pytest

from raspberry_controller.services.navigation import (
    DirectedConnection,
    LaravelRoutePlanner,
    PhysicalNavigationMap,
    PhysicalNode,
    PhysicalRoom,
    ReturnRoute,
    RouteDecision,
    RouteStep,
    UnknownMarkerError,
)


def approved_navigation_map() -> PhysicalNavigationMap:
    nodes = (
        PhysicalNode(1, "NODE_0", "intersection", 0),
        PhysicalNode(2, "NODE_1", "intersection", 1),
        PhysicalNode(3, "NODE_2", "intersection", 2),
        PhysicalNode(4, "ROOM_1", "room", 11),
        PhysicalNode(5, "ROOM_2", "room", 12),
        PhysicalNode(6, "ROOM_3", "room", 13),
        PhysicalNode(7, "ROOM_4", "room", 14),
        PhysicalNode(8, "ROOM_5", "room", 15),
    )
    rooms = tuple(
        PhysicalRoom(
            id=room_number,
            room_number=str(room_number),
            room_name=f"Room {room_number}",
            destination_node=f"ROOM_{room_number}",
            destination_marker_id=10 + room_number,
        )
        for room_number in range(1, 6)
    )
    connections = (
        DirectedConnection("NODE_0", "ROOM_1", RouteDecision.LEFT),
        DirectedConnection("NODE_0", "NODE_1", RouteDecision.STRAIGHT),
        DirectedConnection("NODE_1", "NODE_2", RouteDecision.LEFT),
        DirectedConnection("NODE_1", "ROOM_4", RouteDecision.RIGHT),
        DirectedConnection("NODE_1", "ROOM_5", RouteDecision.STRAIGHT),
        DirectedConnection("NODE_2", "ROOM_3", RouteDecision.LEFT),
        DirectedConnection("NODE_2", "ROOM_2", RouteDecision.RIGHT),
    )
    return_routes = (
        ReturnRoute(1, (RouteStep("ROOM_1", RouteDecision.U_TURN, "NODE_0"),)),
        ReturnRoute(2, (
            RouteStep("ROOM_2", RouteDecision.U_TURN, "NODE_2"),
            RouteStep("NODE_2", RouteDecision.LEFT, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.RIGHT, "NODE_0"),
        )),
        ReturnRoute(3, (
            RouteStep("ROOM_3", RouteDecision.U_TURN, "NODE_2"),
            RouteStep("NODE_2", RouteDecision.RIGHT, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.RIGHT, "NODE_0"),
        )),
        ReturnRoute(4, (
            RouteStep("ROOM_4", RouteDecision.U_TURN, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.LEFT, "NODE_0"),
        )),
        ReturnRoute(5, (
            RouteStep("ROOM_5", RouteDecision.U_TURN, "NODE_1"),
            RouteStep("NODE_1", RouteDecision.STRAIGHT, "NODE_0"),
        )),
    )
    return PhysicalNavigationMap(rooms, nodes, connections, return_routes)


@pytest.mark.parametrize(
    ("room_id", "expected_steps"),
    [
        (1, [("NODE_0", "LEFT", "ROOM_1")]),
        (
            2,
            [
                ("NODE_0", "STRAIGHT", "NODE_1"),
                ("NODE_1", "LEFT", "NODE_2"),
                ("NODE_2", "RIGHT", "ROOM_2"),
            ],
        ),
        (
            3,
            [
                ("NODE_0", "STRAIGHT", "NODE_1"),
                ("NODE_1", "LEFT", "NODE_2"),
                ("NODE_2", "LEFT", "ROOM_3"),
            ],
        ),
        (
            4,
            [
                ("NODE_0", "STRAIGHT", "NODE_1"),
                ("NODE_1", "RIGHT", "ROOM_4"),
            ],
        ),
        (
            5,
            [
                ("NODE_0", "STRAIGHT", "NODE_1"),
                ("NODE_1", "STRAIGHT", "ROOM_5"),
            ],
        ),
    ],
)
def test_exact_approved_routes(
    room_id: int,
    expected_steps: list[tuple[str, str, str]],
) -> None:
    plan = LaravelRoutePlanner(approved_navigation_map()).plan(0, room_id)

    assert [
        (step.from_node, step.direction.value, step.to_node)
        for step in plan.steps
    ] == expected_steps
    assert plan.decision.value == expected_steps[0][1]
    assert plan.next_node == expected_steps[0][2]


@pytest.mark.parametrize(
    ("marker_id", "node_name"),
    [(0, "NODE_0"), (1, "NODE_1"), (2, "NODE_2")],
)
def test_intersection_markers_resolve_through_laravel_map(
    marker_id: int,
    node_name: str,
) -> None:
    node = approved_navigation_map().node_for_marker(marker_id)

    assert node is not None
    assert node.name == node_name


@pytest.mark.parametrize(
    ("room_id", "marker_id"),
    [(1, 11), (2, 12), (3, 13), (4, 14), (5, 15)],
)
def test_room_marker_arrives_only_at_its_own_destination(
    room_id: int,
    marker_id: int,
) -> None:
    planner = LaravelRoutePlanner(approved_navigation_map())

    arrived = planner.plan(marker_id, room_id)
    wrong_destination = planner.plan(marker_id, (room_id % 5) + 1)

    assert arrived.decision is RouteDecision.ARRIVED
    assert arrived.next_node is None
    assert wrong_destination.decision is RouteDecision.NO_ROUTE


def test_unknown_marker_is_rejected_safely() -> None:
    planner = LaravelRoutePlanner(approved_navigation_map())

    with pytest.raises(UnknownMarkerError, match="99"):
        planner.plan(99, 1)


def test_missing_directed_path_returns_no_route() -> None:
    plan = LaravelRoutePlanner(approved_navigation_map()).plan(2, 4)

    assert plan.current_node.name == "NODE_2"
    assert plan.destination_node.name == "ROOM_4"
    assert plan.decision is RouteDecision.NO_ROUTE
    assert plan.steps == ()


@pytest.mark.parametrize(
    ("room_id", "marker_id", "expected_steps"),
    [
        (1, 11, [("ROOM_1", "U_TURN", "NODE_0")]),
        (2, 12, [
            ("ROOM_2", "U_TURN", "NODE_2"),
            ("NODE_2", "LEFT", "NODE_1"),
            ("NODE_1", "RIGHT", "NODE_0"),
        ]),
        (3, 13, [
            ("ROOM_3", "U_TURN", "NODE_2"),
            ("NODE_2", "RIGHT", "NODE_1"),
            ("NODE_1", "RIGHT", "NODE_0"),
        ]),
        (4, 14, [
            ("ROOM_4", "U_TURN", "NODE_1"),
            ("NODE_1", "LEFT", "NODE_0"),
        ]),
        (5, 15, [
            ("ROOM_5", "U_TURN", "NODE_1"),
            ("NODE_1", "STRAIGHT", "NODE_0"),
        ]),
    ],
)
def test_exact_approved_return_routes(
    room_id: int,
    marker_id: int,
    expected_steps: list[tuple[str, str, str]],
) -> None:
    planner = LaravelRoutePlanner(approved_navigation_map())
    plan = planner.plan_return(marker_id, room_id)

    assert [
        (step.from_node, step.direction.value, step.to_node)
        for step in plan.steps
    ] == expected_steps
    assert planner.plan_return(0, room_id).decision is RouteDecision.ARRIVED
