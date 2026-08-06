"""SQLAlchemy configuration and database models for the Raspberry Pi backend."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

DB_NAME = "hospital.db"
DB_PATH = Path(__file__).with_name(DB_NAME)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all SQLite models."""


class Direction(str, Enum):
    """Supported movement directions between nodes."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"
    STRAIGHT = "STRAIGHT"


class MissionStatus(str, Enum):
    """Lifecycle states for dispatched robot missions."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Room(Base):
    """Physical room record mapped to a navigation node."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    room_name: Mapped[str] = mapped_column(String(120), nullable=False)
    destination_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id"), nullable=True, index=True
    )

    destination_node: Mapped["Node | None"] = relationship(
        back_populates="destination_rooms",
        foreign_keys=[destination_node_id],
    )
    missions: Mapped[list["Mission"]] = relationship(back_populates="room")


class Node(Base):
    """Graph node used for mapping the hospital layout."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    node_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    destination_rooms: Mapped[list[Room]] = relationship(
        back_populates="destination_node",
        foreign_keys="Room.destination_node_id",
    )
    outgoing_connections: Mapped[list["Connection"]] = relationship(
        back_populates="from_node",
        foreign_keys="Connection.from_node_id",
    )
    incoming_connections: Mapped[list["Connection"]] = relationship(
        back_populates="to_node",
        foreign_keys="Connection.to_node_id",
    )
    robot_statuses: Mapped[list["RobotStatus"]] = relationship(
        back_populates="current_node"
    )


class Connection(Base):
    """Directed relationship between two navigation nodes."""

    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("from_node_id != to_node_id", name="ck_connections_not_self"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id"), nullable=False, index=True
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id"), nullable=False, index=True
    )
    direction: Mapped[Direction] = mapped_column(
        SQLAlchemyEnum(Direction, native_enum=False, validate_strings=True),
        nullable=False,
    )

    from_node: Mapped[Node] = relationship(
        back_populates="outgoing_connections",
        foreign_keys=[from_node_id],
    )
    to_node: Mapped[Node] = relationship(
        back_populates="incoming_connections",
        foreign_keys=[to_node_id],
    )


class Medicine(Base):
    """Inventory record for medicines available to be dispensed."""

    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    medicine_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    missions: Mapped[list["Mission"]] = relationship(back_populates="medicine")


class Mission(Base):
    """Task representing a medicine dispatch request tied to a room."""

    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MissionStatus] = mapped_column(
        SQLAlchemyEnum(MissionStatus, native_enum=False, validate_strings=True),
        nullable=False,
        default=MissionStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    room: Mapped[Room] = relationship(back_populates="missions")
    medicine: Mapped[Medicine] = relationship(back_populates="missions")


class RobotStatus(Base):
    """Current runtime state of the robot, including node and battery."""

    __tablename__ = "robot_status"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    current_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id"), nullable=True, index=True
    )
    battery: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="IDLE")

    current_node: Mapped["Node | None"] = relationship(
        back_populates="robot_statuses",
        foreign_keys=[current_node_id],
    )


def init_db() -> None:
    """Create all database tables if they do not already exist."""

    Base.metadata.create_all(bind=engine)
