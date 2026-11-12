"""Single inference owner for bounded live inputs and resumable video jobs."""

from __future__ import annotations

from collections import deque
from datetime import timedelta, timezone
import hashlib
import io
import logging
import json
import time

import cv2
import numpy as np
from PIL import Image
from sqlalchemy import or_, select, text

from safesight.config import read_yaml, settings, within
from safesight.inference.engine import Engine
from safesight.inference.state import dumps, loads, blob_references
from safesight.ingestion.video import frames, write_video
from safesight.model_loaders.registry import Registry
from safesight.storage.database import database
from safesight.storage.schema import (
    Evidence,
    FramePacket,
    Incident,
    IncidentPrediction,
    Job,
    Location,
    ModelVersion,
    RuntimeSnapshot,
    Source,
    SystemState,
    identifier,
    utcnow,
)

LOG = logging.getLogger(__name__)


class Worker:
    """Own model instances and temporal state in one process."""

    def __init__(self, config: dict | None = None):
        self.config = config or settings()
        self.db_engine, self.sessions = database(self.config["database_url"])
        self.owner_connection = None
        if self.db_engine.dialect.name == "postgresql":
            self.owner_connection = self.db_engine.connect()
            if not self.owner_connection.scalar(text("SELECT pg_try_advisory_lock(73624411)")):
                self.owner_connection.close()
                raise RuntimeError("Another SafeSight worker already owns this database")
        self.registry = Registry(
            self.config["models_root"],
            self.config["evaluation_mode"],
            pose_asset=read_yaml(self.config["inference_config"])["pose_asset"],
        )
        self.policy = self.registry.temporal_policy(read_yaml(self.config["inference_config"]))
        self.thresholds = {s: dict(a.card.thresholds) for s, a in self.registry.adapters.items()}
        self.fusion_enabled = False
        fusion_path = self.registry.root / "fusion_card.json"
        if fusion_path.exists():
            fusion = json.loads(fusion_path.read_text())
            matching = set(fusion.get("models", {})) == {"cigarette_smoking", "fire_smoke"} and all(
                s in self.registry.adapters
                and (self.registry.root / s / "model_card.json").exists()
                and hashlib.sha256((self.registry.root / s / "model_card.json").read_bytes()).hexdigest() == digest
                for s, digest in fusion.get("models", {}).items()
            )
            if fusion.get("status") == "PASS" and matching and fusion.get("policy") == self.policy:
                self.fusion_enabled = True
                self.thresholds.update(fusion["thresholds"])
        self.registry.status["fusion"] = {
            "ready": self.fusion_enabled,
            "reason": None if self.fusion_enabled else "Joint validation required; unresolved smoke remains reviewable",
        }
        self.fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "policy": self.policy,
                    "thresholds": self.thresholds,
                    "fusion": self.fusion_enabled,
                    "models": {s: a.card.model_dump() for s, a in self.registry.adapters.items()},
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self.media = self.config["media_root"]
        self.last_recovery_gc = 0.0
        self.engines, self.buffers, self.captures, self.pending = {}, {}, {}, {}
        self.worker_id = identifier()
        self.video_jobs = {}
        self.adapter_buffers = {}
        self.model_ids = {}
        with self.sessions.begin() as db:
            # The PostgreSQL owner lock proves the previous worker is no longer active.
            for job in db.scalars(select(Job).where(Job.state == "running")):
                job.state, job.worker_id, job.lease_until = "paused", None, None
            recovered = set()
            for snapshot in db.scalars(select(RuntimeSnapshot)):
                if snapshot.fingerprint != self.fingerprint:
                    db.delete(snapshot)
                    continue
                try:
                    state = loads(snapshot.payload, self.get_blob)
                except (OSError, ValueError, KeyError) as error:
                    LOG.error("Recovery state unavailable: %s", error)
                    db.delete(snapshot)
                    continue
                self.engines[snapshot.key] = state["engine"]
                self.buffers[snapshot.key] = state["buffer"]
                self.adapter_buffers.update(state["adapters"])
                for evidence_id, pending in state["pending"].items():
                    evidence = db.get(Evidence, evidence_id)
                    if evidence and evidence.state == "pending":
                        self.pending[evidence_id] = pending
                        recovered.add(evidence_id)
            for evidence in db.scalars(select(Evidence).where(Evidence.state == "pending")):
                if evidence.id not in recovered:
                    evidence.state, evidence.error = (
                        "failed",
                        "Recovery snapshot unavailable or incompatible with selected model artifacts",
                    )
            for slug, adapter in self.registry.adapters.items():
                card = adapter.card
                row = db.scalar(
                    select(ModelVersion).where(ModelVersion.slug == slug, ModelVersion.run_id == card.run_id)
                )
                if row is None:
                    row = ModelVersion(
                        slug=slug,
                        run_id=card.run_id,
                        card_hash=hashlib.sha256(card.model_dump_json().encode()).hexdigest(),
                        artifact_hash=card.sha256,
                        quality=card.quality,
                    )
                    db.add(row)
                    db.flush()
                self.model_ids[slug] = row.id

    def checkpoint(self, db, key: str) -> None:
        """Commit context in the same transaction as incident creation."""
        state = {
            "engine": self.engines[key],
            "buffer": self.buffers[key],
            "adapters": {k: v for k, v in self.adapter_buffers.items() if k[0] == key},
            "pending": {k: v for k, v in self.pending.items() if v[0] == key},
        }
        snapshot = db.get(RuntimeSnapshot, key)
        if snapshot is None:
            snapshot = RuntimeSnapshot(key=key)
            db.add(snapshot)
        snapshot.fingerprint, snapshot.payload, snapshot.updated_at = (
            self.fingerprint,
            dumps(state, self.put_blob),
            utcnow(),
        )

    def put_blob(self, data: bytes) -> str:
        """Write each immutable media block once before committing its reference."""
        digest = hashlib.sha256(data).hexdigest()
        path = within(self.media, f"recovery/{digest[:2]}/{digest}.bin")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        return digest

    def get_blob(self, digest: str) -> bytes:
        """Reject invalid identifiers and corrupted recovery blocks."""
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid recovery blob identifier")
        data = within(self.media, f"recovery/{digest[:2]}/{digest}.bin").read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Recovery blob checksum mismatch")
        return data

    def collect_recovery_blobs(self) -> None:
        """Discard obsolete raw windows while retaining every committed snapshot block."""
        referenced = set()
        with self.sessions() as db:
            for payload in db.scalars(select(RuntimeSnapshot.payload)):
                referenced.update(blob_references(payload))
        root = within(self.media, "recovery")
        for path in root.rglob("*.bin"):
            if len(path.stem) == 64 and all(c in "0123456789abcdef" for c in path.stem) and path.stem not in referenced:
                within(self.media, path.relative_to(self.media)).unlink(missing_ok=True)
        self.last_recovery_gc = time.monotonic()

    def heartbeat(self) -> None:
        with self.sessions.begin() as db:
            row = db.get(SystemState, "worker")
            if row is None:
                row = SystemState(key="worker")
                db.add(row)
            row.value = {"models": self.registry.status, "worker_id": self.worker_id}
            row.updated_at = utcnow()

    def process(
        self, source: Source, rgb: np.ndarray, timestamp: float, captured_at=None, session_key: str = ""
    ) -> None:
        key = f"{source.id}:{source.generation}:{session_key}"
        if key not in self.engines:
            config = dict(self.policy)
            with self.sessions() as db:
                location = db.get(Location, source.location_id)
                if location and location.policies.get("body_state"):
                    config["body_state"] = {**config["body_state"], **location.policies["body_state"]}
            self.engines[key] = Engine(
                config, self.thresholds, {**source.config, "fusion_enabled": self.fusion_enabled}
            )
            self.buffers[key] = deque(maxlen=int(self.config["sample_fps"] * 30))
        buffer = self.buffers[key]
        if buffer and timestamp <= buffer[-1][0]:
            return  # A committed frame replayed after a crash must not create another incident.
        output = io.BytesIO()
        Image.fromarray(rgb).save(output, format="JPEG", quality=85)
        buffer.append((timestamp, output.getvalue()))
        predictions = []
        for slug in source.enabled_models:
            adapter = self.registry.adapters.get(slug)
            if adapter:
                if hasattr(adapter, "buffer"):
                    adapter.buffer = self.adapter_buffers.setdefault(
                        (key, slug), deque(maxlen=adapter.card.sequence_length)
                    )
                    adapter.source_config = source.config
                try:
                    predictions.append(adapter.predict(rgb, timestamp))
                except (RuntimeError, ValueError) as error:
                    LOG.exception("Inference failed for %s", slug)
                    self.registry.status[slug] = {"ready": False, "reason": str(error)}
        people = self.registry.pose.extract(rgb) if self.registry.pose else []
        alerts = self.engines[key].process(predictions, people, timestamp)
        with self.sessions.begin() as db:
            current = db.get(Source, source.id)
            current.health = {
                **current.health,
                "status": "processing",
                "unknown": self.engines[key].unknown,
                "missing_models": [
                    s for s in source.enabled_models if not self.registry.status.get(s, {}).get("ready")
                ],
            }
            for alert in alerts:
                candidate = alert.candidate
                event_key = session_key + alert.event_id
                row = db.scalar(
                    select(Incident).where(Incident.source_id == source.id, Incident.event_key == event_key)
                )
                if row:
                    row.end_offset, row.score = alert.end, max(row.score, candidate.score)
                    row.end_at = captured_at
                    continue
                adapter = self.registry.adapters[candidate.slug]
                row = Incident(
                    source_id=source.id,
                    location_id=source.location_id,
                    event_key=event_key,
                    slug=candidate.slug,
                    subtype=candidate.subtype,
                    track_id=candidate.track_id,
                    start_offset=alert.start,
                    end_offset=alert.end,
                    start_at=captured_at - timedelta(seconds=timestamp - alert.start) if captured_at else None,
                    end_at=captured_at,
                    score=candidate.score,
                    uncertain=candidate.uncertain,
                    evaluation_only=adapter.card.synthetic or adapter.card.quality["status"] != "PASS",
                    details=candidate.details,
                )
                db.add(row)
                db.flush()
                db.add(
                    IncidentPrediction(
                        incident_id=row.id, model_version_id=self.model_ids[candidate.slug], details=candidate.details
                    )
                )
                relative = f"evidence/{row.id}/frame.jpg"
                path = within(self.media, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(output.getvalue())
                db.add(
                    Evidence(
                        incident_id=row.id,
                        kind="frame",
                        state="ready",
                        path=relative,
                        checksum=hashlib.sha256(output.getvalue()).hexdigest(),
                    )
                )
                clip = Evidence(incident_id=row.id, kind="clip", state="pending")
                db.add(clip)
                db.flush()
                self.pending[clip.id] = (
                    key,
                    alert.start
                    - (20 if candidate.slug == "entrance_guard" else self.config["evidence_before_seconds"]),
                    timestamp + self.config["evidence_after_seconds"],
                )
            self.checkpoint(db, key)
        self.flush_clips(timestamp, key)

    def flush_clips(self, timestamp: float, key: str, force: bool = False) -> None:
        for evidence_id, (source_key, start, end) in list(self.pending.items()):
            if source_key != key or (not force and timestamp < end):
                continue
            with self.sessions.begin() as db:
                row = db.get(Evidence, evidence_id)
                try:
                    retained = [(t, raw) for t, raw in self.buffers[key] if start <= t <= end]
                    selected = [np.asarray(Image.open(io.BytesIO(raw)).convert("RGB")) for _, raw in retained]
                    relative = f"evidence/{row.incident_id}/clip.mp4"
                    path = within(self.media, relative)
                    write_video(path, selected, self.config["sample_fps"], timestamps=[t for t, _ in retained])
                    row.path, row.state = relative, "ready"
                    row.checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                except Exception as error:
                    LOG.exception("Evidence encoding failed")
                    row.state, row.error = "failed", str(error)
            del self.pending[evidence_id]
        if key in self.engines:
            with self.sessions.begin() as db:
                self.checkpoint(db, key)

    def tick(self) -> bool:
        self.release_finished_sessions()
        if time.monotonic() - self.last_recovery_gc > 30:
            self.collect_recovery_blobs()
        self.heartbeat()
        with self.sessions.begin() as db:
            source = db.scalar(select(Source).where(Source.active.is_(True)))
            if source:
                if source.kind == "browser":
                    packet = db.scalar(
                        select(FramePacket)
                        .where(FramePacket.source_id == source.id)
                        .order_by(FramePacket.sequence)
                        .with_for_update(skip_locked=True)
                    )
                    if packet:
                        path = within(self.media, packet.path)
                        try:
                            rgb = np.asarray(Image.open(path).convert("RGB"))
                            self.process(source, rgb, packet.timestamp, packet.captured_at)
                        except (OSError, ValueError, RuntimeError) as error:
                            LOG.exception("Live frame processing failed")
                            source.active = False
                            source.health = {**source.health, "status": "failed", "error": str(error)}
                        db.delete(packet)
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            LOG.exception("Could not remove consumed spool packet")
                        return True
                    if source.last_frame_at and utcnow() - source.last_frame_at.replace(
                        tzinfo=timezone.utc
                    ) > timedelta(seconds=self.config["source_timeout_seconds"]):
                        source.active = False
                        source.health = {**source.health, "status": "disconnected"}
                    else:
                        return False
                else:
                    if source.id not in self.captures:
                        self.captures[source.id] = cv2.VideoCapture(
                            source.config.get("uri") if source.kind == "rtsp" else source.config.get("device", 0)
                        )
                    ok, bgr = self.captures[source.id].read()
                    if not ok:
                        source.active = False
                        source.health = {"status": "capture_failed"}
                    else:
                        self.process(source, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), time.monotonic(), utcnow())
                        time.sleep(1 / self.config["sample_fps"])
                        return True
            job = db.scalar(
                select(Job)
                .where(
                    or_(Job.state.in_(["queued", "paused"]), (Job.state == "running") & (Job.lease_until < utcnow()))
                )
                .order_by(Job.created_at)
                .with_for_update(skip_locked=True)
            )
            if not job:
                # Continue a job already leased to this worker.
                job = db.scalar(select(Job).where(Job.state == "running", Job.worker_id == self.worker_id))
            if not job:
                return False
            job.state, job.worker_id = "running", self.worker_id
            job.lease_until = utcnow() + timedelta(seconds=self.config["worker_lease_seconds"])
            source = db.get(Source, job.source_id)
            if job.id not in self.video_jobs:
                self.video_jobs[job.id] = iter(frames(within(self.media, job.path), self.config["sample_fps"]))
            try:
                timestamp, rgb = next(self.video_jobs[job.id])
                while timestamp <= job.cursor:
                    timestamp, rgb = next(self.video_jobs[job.id])
                self.process(
                    source,
                    rgb,
                    timestamp,
                    job.captured_at + timedelta(seconds=timestamp) if job.captured_at else None,
                    job.id,
                )
                job.cursor = timestamp
            except StopIteration:
                job.state = "completed"
                key = f"{source.id}:{source.generation}:{job.id}"
                if key in self.buffers:
                    self.flush_clips(job.cursor, key, force=True)
                    snapshot = db.get(RuntimeSnapshot, key)
                    if snapshot:
                        db.delete(snapshot)
                    self.buffers.pop(key, None)
                    self.engines.pop(key, None)
                    for buffer_key in [k for k in self.adapter_buffers if k[0] == key]:
                        self.adapter_buffers.pop(buffer_key, None)
                self.video_jobs.pop(job.id, None)
            except Exception as error:
                LOG.exception("Job failed")
                job.state, job.error = "failed", str(error)
            return True

    def release_finished_sessions(self) -> None:
        """Finalize stopped sessions and keep memory/snapshots bounded across jobs."""
        for key in list(self.engines):
            source_id, generation, job_id = key.split(":", 2)
            with self.sessions() as db:
                source = db.get(Source, source_id)
                job = db.get(Job, job_id) if job_id else None
                finished = (
                    (job is None or job.state in ("completed", "failed"))
                    if job_id
                    else (source is None or not source.active or source.generation != int(generation))
                )
            if not finished:
                continue
            self.flush_clips(self.buffers[key][-1][0] if self.buffers[key] else 0, key, force=True)
            with self.sessions.begin() as db:
                snapshot = db.get(RuntimeSnapshot, key)
                if snapshot:
                    db.delete(snapshot)
            self.engines.pop(key, None)
            self.buffers.pop(key, None)
            for adapter_key in [k for k in self.adapter_buffers if k[0] == key]:
                self.adapter_buffers.pop(adapter_key, None)
            capture = self.captures.pop(source_id, None)
            if capture:
                capture.release()

    def close(self) -> None:
        for capture in self.captures.values():
            capture.release()
        self.registry.close()
        if self.owner_connection is not None:
            self.owner_connection.close()
        self.db_engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker = Worker()
    try:
        while True:
            if not worker.tick():
                time.sleep(0.2)
    except KeyboardInterrupt:
        LOG.info("Worker stopped")
    finally:
        worker.close()


if __name__ == "__main__":
    main()
