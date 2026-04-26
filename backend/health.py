"""Health check router shared across all vite-fastapi-sqlite apps."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from app.database import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str = "sqlite"


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_session)) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ok")
