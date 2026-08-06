"""Mission request and response schemas for the FastAPI API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, StrictInt


class MissionCreateRequest(BaseModel):
    """Payload used to create a new mission."""

    room_id: StrictInt = Field(..., ge=1)
    medicine_id: StrictInt = Field(..., ge=1)
    quantity: StrictInt = Field(..., ge=1)


class MissionStartRequest(BaseModel):
    """Optional payload used when starting a mission."""

    current_node: StrictInt | None = Field(default=None, ge=0)


class MissionResponse(BaseModel):
    """Mission entity returned by the API."""

    id: int
    room_id: int
    medicine_id: int
    quantity: int
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class MissionStatusResponse(BaseModel):
    """Mission start response with the navigation decision."""

    mission_id: int
    current_node: int
    next_direction: str
    status: str
