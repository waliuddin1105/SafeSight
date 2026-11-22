"""Single inference owner for bounded live inputs and resumable video jobs."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta, timezone
import hashlib
import io
import logging
import json
import time

import cv2
import numpy as np
from PIL import Image
from sqlalchemy import delete, select, text

from safesight.config import read_yaml, settings, within
from safesight.inference.engine import Engine
from safesight.inference.state import dumps, loads, blob_references
from safesight.ingestion.video import write_video
from safesight.model_loaders.registry import Registry
from safesight.contracts.model_card import contract_sha256
from safesight.storage.database import database
from safesight.storage.schema import (
    Evidence,
    FramePacket,
    Incident,
    IncidentPrediction,
    Job,
    JobFrame,
    AuthSession,
    LoginAttempt,
    Location,
    ModelVersion,
    RuntimeSnapshot,
    Source,
    SystemState,
    identifier,
    utcnow,
)

LOG = logging.getLogger(__name__)

POSE_CONTEXT_MODELS = frozenset({"body_state", "phone_usage", "cigarette_smoking", "entrance_guard"})


def needs_pose_context(enabled_models, available_models) -> bool:
    """Return whether selected, loadable models consume person keypoints or tracks."""
    return bool(POSE_CONTEXT_MODELS.intersection(enabled_models).intersection(available_models))


class Worker:
    """Own model instances and temporal state in one process."""

    def __init__(self, config: dict | None = None):
        self.config = config or settings()
        self.db_engine, self.sessions = database(self.config["database_url"])
        self.owner_connection = None
        self.owner_pid = None
        if self.db_engine.dialect.name == "postgresql":
            self.owner_connection = self.db_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            if not self.owner_connection.scalar(text("SELECT pg_try_advisory_lock(73624411)")):
                self.owner_connection.close()
                raise RuntimeError("Another SafeSight worker already owns this database")
        if self.owner_connection is not None:
            self.owner_pid = self.owner_connection.scalar(text("SELECT pg_backend_pid()"))
        self.registry = Registry(
            self.config["models_root"],
            self.config["evaluation_mode"],
            pose_asset=read_yaml(self.config["inference_config"])["pose_asset"],
            lazy=True,
        )
        self.policy = self.registry.temporal_policy(read_yaml(self.config["inference_config"]))
        self.thresholds = {s: dict(values) for s, values in self.registry.event_thresholds.items()}
        self.fusion_enabled = False
        fusion_path = self.registry.root / "fusion_card.json"
        if fusion_path.exists():
            fusion = json.loads(fusion_path.read_text())
            matching = set(fusion.get("models", {})) == {"cigarette_smoking", "fire_smoke"} and all(
                s in self.registry.cards
                and contract_sha256(self.registry.cards[s]) == digest
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
                    "models": {s: card.model_dump() for s, card in self.registry.cards.items()},
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self.media = self.config["media_root"]
        self.last_recovery_gc = 0.0
        self.last_session_cleanup = 0.0
        self.last_heartbeat = 0.0
        self.engines, self.buffers, self.captures, self.pending = {}, {}, {}, {}
        self.evidence_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="safesight-evidence")
        self.evidence_tasks = {}
        self.worker_id = identifier()
        self.video_jobs = {}
        self.job_retries = {}
        self.adapter_buffers = {}
        self.model_ids = {}
        self.job_contexts = {}
        self.processing_job = None
        with self.sessions.begin() as db:
            # The PostgreSQL owner lock proves the previous worker is no longer active.
            for job in db.scalars(select(Job).where(Job.state == "running")):
                job.state, job.worker_id, job.lease_until = "paused", None, None
            recovered = set()
            for snapshot in db.scalars(select(RuntimeSnapshot)):
                job_id = snapshot.key.split(":", 2)[-1]
                saved_job = db.get(Job, job_id) if job_id else None
                expected = (
                    saved_job.snapshot.get("fingerprint") if saved_job and saved_job.snapshot else self.fingerprint
                )
                if snapshot.fingerprint != expected:
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
            for slug, card in self.registry.cards.items():
                row = db.scalar(
                    select(ModelVersion).where(ModelVersion.slug == slug, ModelVersion.run_id == card.run_id)
                )
                if row is None:
                    row = ModelVersion(
                        slug=slug,
                        run_id=card.run_id,
                        card_hash=contract_sha256(card),
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
        self.assert_owner()
        with self.sessions.begin() as db:
            row = db.get(SystemState, "worker")
            if row is None:
                row = SystemState(key="worker")
                db.add(row)
            row.value = {"models": self.registry.status, "worker_id": self.worker_id}
            row.updated_at = utcnow()

    def process(
        self, source: Source, rgb: np.ndarray, timestamp: float, captured_at=None, session_key: str = "",
        *, db=None, prepared: dict | None = None, packet_id: str | None = None,
    ) -> None:
        self.registry.activate(set(source.enabled_models))
        key = f"{source.id}:{source.generation}:{session_key}"
        if key not in self.engines:
            config = dict(self.policy)
            if session_key and "location_policies" in source.config:
                policies = source.config["location_policies"]
            else:
                with self.sessions() as location_db:
                    location = location_db.get(Location, source.location_id)
                    policies = location.policies if location else {}
            if policies.get("body_state"):
                config["body_state"] = {**config["body_state"], **policies["body_state"]}
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
        people = prepared["people"] if prepared is not None else (
            self.registry.pose.extract(rgb)
            if self.registry.pose and needs_pose_context(source.enabled_models, self.registry.adapters)
            else []
        )
        for slug in source.enabled_models:
            adapter = self.registry.adapters.get(slug)
            if adapter:
                if hasattr(adapter, "buffer"):
                    adapter.buffer = self.adapter_buffers.setdefault(
                        (key, slug), deque(maxlen=adapter.card.sequence_length)
                    )
                    adapter.source_config = source.config
                try:
                    if prepared is not None:
                        if slug in prepared["predictions"]:
                            predictions.append(prepared["predictions"][slug])
                    elif slug == "body_state":
                        predictions.append(adapter.predict(rgb, timestamp, people=people))
                    else:
                        predictions.append(adapter.predict(rgb, timestamp))
                except (RuntimeError, ValueError) as error:
                    LOG.exception("Inference failed for %s", slug)
                    self.registry.status[slug] = {"ready": False, "reason": str(error)}
        alerts = self.engines[key].process(predictions, people, timestamp)
        if db is None:
            self.assert_owner()
        with (self.sessions.begin() if db is None else nullcontext(db)) as transaction:
            db = transaction
            if session_key:
                existing_frame = db.scalar(
                    select(JobFrame).where(JobFrame.job_id == session_key, JobFrame.timestamp == timestamp)
                )
                if existing_frame is None:
                    db.add(
                        JobFrame(
                            job_id=session_key,
                            timestamp=timestamp,
                            predictions=[
                                {
                                    "slug": p.slug,
                                    "model_version": p.model_version,
                                    "scores": p.scores,
                                    "unknown_reason": p.unknown_reason,
                                    "detections": [
                                        {"label": d.label, "score": d.score, "box": list(d.box), "track_id": d.track_id}
                                        for d in p.detections
                                    ],
                                }
                                for p in predictions
                            ],
                            unknown=dict(self.engines[key].unknown),
                        )
                    )
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
            if not session_key or prepared is None:
                self.checkpoint(db, key)
            if packet_id is not None:
                consumed = db.get(FramePacket, packet_id)
                if consumed:
                    db.delete(consumed)
        if prepared is None:
            self.flush_clips(timestamp, key)

    def flush_clips(self, timestamp: float, key: str, force: bool = False) -> None:
        from safesight.model_loaders.registry import file_sha256

        def encode(relative, retained):
            selected = [np.asarray(Image.open(io.BytesIO(raw)).convert("RGB")) for _, raw in retained]
            path = within(self.media, relative)
            write_video(path, selected, self.config["sample_fps"], timestamps=[t for t, _ in retained])
            return file_sha256(path)

        for evidence_id, (source_key, start, end) in list(self.pending.items()):
            if source_key != key or (not force and timestamp < end):
                continue
            if evidence_id in self.evidence_tasks:
                continue
            with self.sessions() as db:
                row = db.get(Evidence, evidence_id)
                incident_id = row.incident_id if row else None
            if incident_id is None:
                del self.pending[evidence_id]
                continue
            relative = f"evidence/{incident_id}/clip.mp4"
            retained = [(t, raw) for t, raw in self.buffers[key] if start <= t <= end]
            self.evidence_tasks[evidence_id] = (relative, self.evidence_pool.submit(encode, relative, retained))
        self.finish_clips()

    def finish_clips(self) -> None:
        for evidence_id, (relative, task) in list(self.evidence_tasks.items()):
            if not task.done():
                continue
            checksum, failure = None, None
            try:
                checksum = task.result()
            except Exception as error:
                LOG.exception("Evidence encoding failed")
                failure = str(error)
            self.assert_owner()
            with self.sessions.begin() as db:
                row = db.get(Evidence, evidence_id)
                if row:
                    row.path = relative if failure is None else None
                    row.state = "ready" if failure is None else "failed"
                    row.checksum, row.error = checksum, failure
            self.pending.pop(evidence_id, None)
            del self.evidence_tasks[evidence_id]

    def assert_owner(self) -> None:
        """A lost dedicated advisory-lock connection must stop all writes."""
        if self.owner_connection is not None:
            try:
                pid = self.owner_connection.scalar(text("SELECT pg_backend_pid()"))
                if pid != self.owner_pid:
                    raise RuntimeError("Worker ownership connection was replaced")
            except Exception as error:
                raise RuntimeError("Worker database ownership connection lost; restart worker") from error

    def tick(self) -> bool:
        """Claim briefly, decode/infer outside the transaction, then commit progress."""
        self.finish_clips()
        self.release_finished_sessions()
        if time.monotonic() - self.last_heartbeat >= 5:
            self.heartbeat()
            self.last_heartbeat = time.monotonic()
        packet = None
        with self.sessions() as db:
            source = db.scalar(
                select(Source).where(Source.active.is_(True), Source.kind != "upload").order_by(Source.id)
            )
            if source and source.kind == "browser":
                packet = db.scalar(
                    select(FramePacket)
                    .where(FramePacket.source_id == source.id, FramePacket.generation == source.generation)
                    .order_by(FramePacket.sequence)
                )
        if source:
            if source.kind == "browser":
                if packet:
                    path = within(self.media, packet.path)
                    try:
                        with Image.open(path) as image:
                            rgb = np.asarray(image.convert("RGB"))
                        self.process(source, rgb, packet.timestamp, packet.captured_at, packet_id=packet.id)
                    except (OSError, ValueError) as error:
                        self.fail_source(source.id, "Frame decoding failed")
                        LOG.warning("Frame decoding failed: %s", type(error).__name__)
                        with self.sessions.begin() as db:
                            consumed = db.get(FramePacket, packet.id)
                            if consumed:
                                db.delete(consumed)
                    path.unlink(missing_ok=True)
                    return True
                if source.last_frame_at and utcnow() - source.last_frame_at.replace(tzinfo=timezone.utc) > timedelta(
                    seconds=self.config["source_timeout_seconds"]
                ):
                    self.fail_source(source.id, "disconnected")
                else:
                    return self.tick_job()
            else:
                if source.id not in self.captures:
                    from safesight.ingestion.capture import CaptureReader

                    target = source.config.get("uri") if source.kind == "rtsp" else source.config.get("device", 0)
                    capture = CaptureReader(
                        target,
                        rtsp=source.kind == "rtsp",
                        fps=self.config["sample_fps"],
                        timeout=self.config["decode_timeout_seconds"],
                    )
                    self.captures[source.id] = capture
                ok, bgr = self.captures[source.id].read()
                if not ok:
                    self.fail_source(source.id, "capture_failed")
                else:
                    self.process(source, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), time.monotonic(), utcnow())
                    time.sleep(1 / self.config["sample_fps"])
                    return True
        return self.tick_job()

    def fail_source(self, source_id: str, reason: str) -> None:
        capture = self.captures.pop(source_id, None)
        if capture:
            capture.release()
        self.assert_owner()
        with self.sessions.begin() as db:
            source = db.get(Source, source_id)
            if source:
                source.active = False
                source.health = {**source.health, "status": reason}
        self.release_finished_sessions(force=True)

    def tick_job(self) -> bool:
        from safesight.worker.jobs import process_job

        worked = process_job(self)
        if not worked:
            self.maintenance()
        return worked

    def maintenance(self) -> None:
        """Run filesystem/database housekeeping only while inference is idle."""
        if time.monotonic() - self.last_recovery_gc < 300:
            return
        self.assert_owner()
        self.collect_recovery_blobs()
        with self.sessions.begin() as db:
            db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
            db.execute(delete(LoginAttempt).where(LoginAttempt.expires_at < utcnow()))

    def release_finished_sessions(self, force: bool = False) -> None:
        """Finalize stopped sessions using bounded set-based state queries."""
        now = time.monotonic()
        if not force and now - self.last_session_cleanup < 5:
            return
        self.last_session_cleanup = now
        parsed = {key: key.split(":", 2) for key in self.engines}
        if not parsed:
            return
        source_ids = {parts[0] for parts in parsed.values()}
        job_ids = {parts[2] for parts in parsed.values() if parts[2]}
        with self.sessions() as db:
            sources = {
                row.id: row for row in db.scalars(select(Source).where(Source.id.in_(source_ids)))
            }
            jobs = {
                row.id: row for row in db.scalars(select(Job).where(Job.id.in_(job_ids)))
            } if job_ids else {}
        releasable = []
        for key, (source_id, generation, job_id) in parsed.items():
            source, job = sources.get(source_id), jobs.get(job_id) if job_id else None
            finished = (
                (job is None or job.state in ("completed", "failed", "cancelled"))
                if job_id
                else (source is None or not source.active or source.generation != int(generation))
            )
            if not finished:
                continue
            self.flush_clips(self.buffers[key][-1][0] if self.buffers[key] else 0, key, force=True)
            if any(item[0] == key for item in self.pending.values()):
                continue
            releasable.append(key)
        if releasable:
            self.assert_owner()
            with self.sessions.begin() as db:
                db.execute(delete(RuntimeSnapshot).where(RuntimeSnapshot.key.in_(releasable)))
        for key in releasable:
            source_id, _generation, job_id = parsed[key]
            if job_id:
                iterator = self.video_jobs.pop(job_id, None)
                if iterator is not None and hasattr(iterator, "close"):
                    iterator.close()
            self.engines.pop(key, None)
            self.buffers.pop(key, None)
            for adapter_key in [k for k in self.adapter_buffers if k[0] == key]:
                self.adapter_buffers.pop(adapter_key, None)
            capture = self.captures.pop(source_id, None)
            if capture:
                capture.release()

    def close(self) -> None:
        self.evidence_pool.shutdown(wait=True)
        self.finish_clips()
        for iterator in self.video_jobs.values():
            if hasattr(iterator, "close"):
                iterator.close()
        for capture in self.captures.values():
            capture.release()
        self.registry.close()
        for registry, _, _, _ in self.job_contexts.values():
            registry.close()
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
