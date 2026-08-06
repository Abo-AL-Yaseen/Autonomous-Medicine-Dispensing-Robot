"""Local simulation for the existing navigation system.

This script intentionally reuses the project's current NavigationGraph and
NavigationService without modifying hardware or API behavior. It exists only to
simulate how the robot would react to ArUco markers during a mission.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from raspberry_controller.navigation.engine import NavigationService
from raspberry_controller.navigation.graph import NavigationGraph

DEFAULT_TARGET_ROOM_ID = 2
DEFAULT_MARKERS = [0, 1, 2, 4]


def _load_graph() -> tuple[NavigationGraph, list[object], list[object], list[object]]:
    graph = NavigationGraph()
    rooms = graph.load_rooms()
    nodes = graph.load_nodes()
    connections = graph.load_connections()
    return graph, rooms, nodes, connections


def _print_result(
    marker: int, target_room_id: int, direction: str, mission_state: str
) -> None:
    print(f"Current marker: {marker}")
    print(f"Target room: {target_room_id}")
    print(f"Returned direction: {direction}")
    print(f"Mission status: {mission_state}")
    print("-" * 32)


def run_simulation(markers: list[int], target_room_id: int = DEFAULT_TARGET_ROOM_ID) -> None:
    """Run one simulated mission against the existing navigation engine."""

    graph, rooms, nodes, connections = _load_graph()
    navigation_service = NavigationService(graph=graph)

    print("Loaded navigation graph")
    print(f"Rooms: {len(rooms)} | Nodes: {len(nodes)} | Connections: {len(connections)}")
    print(f"Mission -> Room {target_room_id}")
    print("-" * 32)

    markers_processed = 0
    mission_state = "ACTIVE"
    last_navigation_decision = "NONE"

    for marker in markers:
        markers_processed += 1

        if graph.get_node(marker) is None:
            last_navigation_decision = "UNKNOWN"
            print(f"Warning: marker {marker} does not exist in the navigation graph.")
            print("Mission should continue.")
            print("-" * 32)
            continue

        direction = navigation_service.next_direction(marker, target_room_id)
        last_navigation_decision = direction

        if direction == "UNKNOWN":
            print("Warning: navigation service returned UNKNOWN for this marker.")
            print("Mission should continue.")
            _print_result(marker, target_room_id, direction, mission_state)
            continue

        if direction == "ARRIVED":
            mission_state = "ARRIVED"
            print("Mission has arrived.")
            _print_result(marker, target_room_id, direction, mission_state)
            print("Mission completed successfully.")
            break

        print("Mission should continue.")
        _print_result(marker, target_room_id, direction, mission_state)

    print("Simulation summary")
    print(f"Target room: {target_room_id}")
    print(f"Number of markers processed: {markers_processed}")
    print(f"Final mission state: {mission_state}")
    print(f"Last navigation decision: {last_navigation_decision}")


def prompt_for_marker() -> int:
    raw = input("Enter the detected ArUco marker ID (or press Enter to exit): ").strip()
    if not raw:
        raise EOFError

    try:
        marker_id = int(raw)
    except ValueError as exc:
        raise ValueError("Marker must be an integer.") from exc
    return marker_id


def interactive_mode() -> None:
    target_room_id = DEFAULT_TARGET_ROOM_ID
    print("Navigation simulation started.")
    print(f"Default target room: {target_room_id}")
    print("Enter marker IDs one at a time. Press Enter to finish.")
    print("-" * 32)

    markers: list[int] = []
    while True:
        try:
            marker = prompt_for_marker()
        except EOFError:
            break
        except ValueError as exc:
            print(f"Invalid input: {exc}")
            continue
        markers.append(marker)

    if not markers:
        markers = DEFAULT_MARKERS.copy()
        print(f"No markers entered; running default sequence: {markers}")

    run_simulation(markers, target_room_id=target_room_id)


if __name__ == "__main__":
    try:
        interactive_mode()
    except KeyboardInterrupt:
        print("\nSimulation cancelled.")
