"""Mission management service for robot delivery tasks.

This layer contains all mission lifecycle logic, while the HTTP layer only calls
this service. It uses NavigationService only to get the next decision and does
not access the hardware controller or ESP32 directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..database import Mission, MissionStatus, RobotStatus, SessionLocal
from ..navigation.engine import NavigationService


class MissionService:
    """Manage robot delivery missions from creation to completion.

    This service coordinates mission state, robot status, and the navigation
    decision flow. The camera layer is responsible only for detecting markers and
    passing the relevant event into this service; the actual route choice remains
    delegated to NavigationService.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        navigation_service: NavigationService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._navigation_service = navigation_service or NavigationService()

    def create_mission(self, room_id: int, medicine_id: int, quantity: int) -> Mission:
        """Create a new mission in the PENDING state."""

        mission = Mission(
            room_id=room_id,
            medicine_id=medicine_id,
            quantity=quantity,
            status=MissionStatus.PENDING,
            created_at=datetime.utcnow(),
            completed_at=None,
        )

        with self._session_factory() as session:
            session.add(mission)
            session.commit()
            session.refresh(mission)
            return mission

    def get_mission(self, mission_id: int) -> Mission | None:
        """Fetch one mission by ID."""

        with self._session_factory() as session:
            return session.get(Mission, mission_id)

    def get_active_mission(self) -> Mission | None:
        """Return the currently running mission if one exists."""

        with self._session_factory() as session:
            return (
                session.query(Mission)
                .filter(Mission.status.in_([MissionStatus.RUNNING, MissionStatus.PENDING]))
                .order_by(Mission.created_at.desc())
                .first()
            )

    def get_mission_history(self) -> list[Mission]:
        """Return all missions ordered from most recent to oldest."""

        with self._session_factory() as session:
            return list(session.query(Mission).order_by(Mission.created_at.desc()).all())

    def start_mission(self, mission_id: int, current_node: int = 0) -> dict[str, Any]:
        """Start a mission and return the next navigation decision."""

        with self._session_factory() as session:
            mission = session.get(Mission, mission_id)
            if mission is None:
                raise ValueError(f"Mission {mission_id} not found")

            if mission.status == MissionStatus.CANCELLED:
                raise ValueError(f"Mission {mission_id} is cancelled")

            if mission.status == MissionStatus.COMPLETED:
                raise ValueError(f"Mission {mission_id} is already completed")

            mission.status = MissionStatus.RUNNING
            session.commit()
            session.refresh(mission)

        next_direction = self._navigation_service.next_direction(current_node, mission.room_id)
        return {
            "mission_id": mission.id,
            "current_node": current_node,
            "next_direction": next_direction,
            "status": mission.status.value,
        }

    def update_robot_status(
        self,
        current_node_id: int | None,
        *,
        battery: int = 100,
        state: str = "IDLE",
    ) -> RobotStatus:
        """Persist the latest robot position and operational state."""

        with self._session_factory() as session:
            robot_status = (
                session.query(RobotStatus)
                .order_by(RobotStatus.id.desc())
                .first()
            )

            if robot_status is None:
                robot_status = RobotStatus(
                    current_node_id=current_node_id,
                    battery=battery,
                    state=state,
                )
                session.add(robot_status)
            else:
                robot_status.current_node_id = current_node_id
                robot_status.battery = battery
                robot_status.state = state

            session.commit()
            session.refresh(robot_status)
            return robot_status

    def handle_node_marker(self, mission_id: int, current_node: int, *, battery: int = 100) -> str:
        """Process a node marker event and return the next navigation decision.

        The camera layer is expected to detect only the marker and pass the node ID
        here. MissionService updates the robot status and delegates the move choice
        to NavigationService.
        """

        with self._session_factory() as session:
            mission = session.get(Mission, mission_id)
            if mission is None:
                raise ValueError(f"Mission {mission_id} not found")

            if mission.status not in (MissionStatus.PENDING, MissionStatus.RUNNING):
                raise ValueError(f"Mission {mission_id} cannot accept new navigation input")

            mission.status = MissionStatus.RUNNING
            session.commit()
            session.refresh(mission)

        self.update_robot_status(current_node, battery=battery, state="FOLLOWING_LINE")
        return self._navigation_service.next_direction(current_node, mission.room_id)

    def handle_room_marker(
        self,
        mission_id: int,
        room_id: int | None = None,
        *,
        current_node: int | None = None,
        battery: int = 100,
    ) -> dict[str, Any]:
        """Process a room marker event.

        Room markers are treated as destination checks only. If they match the
        active mission room, the mission is completed; otherwise the marker is
        ignored and the robot continues its current route.
        """

        with self._session_factory() as session:
            mission = session.get(Mission, mission_id)
            if mission is None:
                raise ValueError(f"Mission {mission_id} not found")

            target_room_id = room_id if room_id is not None else mission.room_id
            if target_room_id == mission.room_id:
                mission.status = MissionStatus.COMPLETED
                mission.completed_at = datetime.utcnow()
                session.commit()
                session.refresh(mission)

        if target_room_id == mission.room_id:
            if current_node is not None:
                self.update_robot_status(current_node, battery=battery, state="AT_ROOM")
            else:
                self.update_robot_status(current_node, battery=battery, state="ARRIVED")
            return {
                "mission_id": mission.id,
                "completed": True,
                "ignored": False,
                "status": mission.status.value,
            }

        if current_node is not None:
            self.update_robot_status(current_node, battery=battery, state="FOLLOWING_LINE")
        else:
            self.update_robot_status(current_node, battery=battery, state="IDLE")

        return {
            "mission_id": mission.id,
            "completed": False,
            "ignored": True,
            "status": mission.status.value,
        }

    def complete_mission(self, mission_id: int) -> Mission:
        """Mark a mission as completed."""

        with self._session_factory() as session:
            mission = session.get(Mission, mission_id)
            if mission is None:
                raise ValueError(f"Mission {mission_id} not found")

            mission.status = MissionStatus.COMPLETED
            mission.completed_at = datetime.utcnow()
            session.commit()
            session.refresh(mission)
            return mission

    def cancel_mission(self, mission_id: int) -> Mission:
        """Mark a mission as cancelled."""

        with self._session_factory() as session:
            mission = session.get(Mission, mission_id)
            if mission is None:
                raise ValueError(f"Mission {mission_id} not found")

            mission.status = MissionStatus.CANCELLED
            mission.completed_at = datetime.utcnow()
            session.commit()
            session.refresh(mission)
            return mission

    def get_missions(self) -> list[Mission]:
        """Return all missions."""

        return self.get_mission_history()
