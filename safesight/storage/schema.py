"""Relational records for sources, leased work, evidence, and review history."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def identifier() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    username: Mapped[str] = mapped_column(String(320), unique=True)
    supabase_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="reviewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Base):
    """Backend-only tokens for a signed, opaque browser session identifier."""

    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Karachi")
    policies: Mapped[dict] = mapped_column(JSON, default=dict)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (CheckConstraint("kind IN ('browser','usb','rtsp','upload')"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(120))
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled_models: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    last_sequence: Mapped[int] = mapped_column(Integer, default=-1)
    last_capture_ms: Mapped[float] = mapped_column(Float, default=-1)
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint("state IN ('queued','running','completed','failed','paused','cancelled')", name="ck_job_state"),
        Index("ix_jobs_state_created", "state", "created_at"),
    )
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    cursor: Mapped[float] = mapped_column(Float, default=-1)
    duration: Mapped[float] = mapped_column(Float, default=0)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_seconds: Mapped[float] = mapped_column(Float, default=0)
    processed_frames: Mapped[int] = mapped_column(Integer, default=0)


class JobFrame(Base):
    __tablename__ = "job_frames"
    __table_args__ = (UniqueConstraint("job_id", "timestamp"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    predictions: Mapped[list] = mapped_column(JSON)
    unknown: Mapped[dict] = mapped_column(JSON)


class FramePacket(Base):
    __tablename__ = "frame_packets"
    __table_args__ = (UniqueConstraint("source_id", "generation", "sequence"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("slug", "run_id"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    slug: Mapped[str] = mapped_column(String(40))
    run_id: Mapped[str] = mapped_column(String(80))
    card_hash: Mapped[str] = mapped_column(String(64))
    artifact_hash: Mapped[str] = mapped_column(String(64))
    quality: Mapped[dict] = mapped_column(JSON)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("source_id", "event_key"),
        CheckConstraint("review_status IN ('pending','confirmed','dismissed')"),
        Index("ix_incidents_filters", "slug", "location_id", "created_at"),
        Index("ix_incidents_review", "review_status", "created_at"),
    )
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    event_key: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(40))
    subtype: Mapped[str] = mapped_column(String(40))
    track_id: Mapped[str] = mapped_column(String(80))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_offset: Mapped[float] = mapped_column(Float)
    end_offset: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    score: Mapped[float] = mapped_column(Float)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluation_only: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class IncidentPrediction(Base):
    __tablename__ = "incident_predictions"
    __table_args__ = (UniqueConstraint("incident_id", "model_version_id"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    details: Mapped[dict] = mapped_column(JSON)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("incident_id", "kind"), CheckConstraint("state IN ('pending','ready','failed')"))
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    path: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    checksum: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)


class Review(Base):
    __tablename__ = "incident_reviews"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=identifier)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuntimeSnapshot(Base):
    """Atomic source context and evidence window, encoded without executable objects."""

    __tablename__ = "runtime_snapshots"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
