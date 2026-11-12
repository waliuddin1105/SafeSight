"""Recording jobs with pinned artifacts, short claims and durable cancellation."""

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import time

from sqlalchemy import or_, select

from safesight.config import within
from safesight.ingestion.video import frames
from safesight.model_loaders.registry import Registry
from safesight.storage.schema import Job, Source, ModelVersion, utcnow


@contextmanager
def pinned(worker, job):
    """Temporarily use the job's exact model cards without activating them globally."""
    snapshot = job.snapshot
    if not snapshot or not snapshot.get("cards"):
        raise ValueError("Legacy job has no pinned models; resubmit the recording")
    key = snapshot["fingerprint"]
    if key not in worker.job_contexts:
        for registry, _, _, _ in worker.job_contexts.values():
            registry.close()
        worker.job_contexts.clear()
        registry = Registry(
            worker.config["models_root"],
            evaluation=snapshot["evaluation"],
            selected={s: f"{s}/model_card.json" for s in snapshot["cards"]},
            cards=snapshot["cards"],
            reusable=worker.registry,
            pose_asset=snapshot["policy"]["pose_asset"],
        )
        if any(not registry.status.get(s, {}).get("ready") for s in snapshot["cards"]):
            registry.close()
            raise ValueError("Pinned artifacts unavailable or incompatible; restore their exact weights/context assets")
        ids = {}
        with worker.sessions.begin() as db:
            for slug, adapter in registry.adapters.items():
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
                ids[slug] = row.id
        policy = registry.temporal_policy(snapshot["policy"])
        thresholds = {s: dict(a.card.thresholds) for s, a in registry.adapters.items()}
        worker.job_contexts[key] = registry, policy, thresholds, ids
    old = worker.registry, worker.policy, worker.thresholds, worker.model_ids, worker.fingerprint, worker.fusion_enabled
    registry, policy, thresholds, ids = worker.job_contexts[key]
    worker.registry, worker.policy, worker.thresholds, worker.model_ids = registry, policy, thresholds, ids
    worker.fingerprint, worker.fusion_enabled = key, False
    fusion = snapshot.get("fusion")
    if fusion and fusion.get("policy") == policy:
        worker.thresholds = {**thresholds, **fusion["thresholds"]}
        worker.fusion_enabled = True
    try:
        yield
    finally:
        (
            worker.registry,
            worker.policy,
            worker.thresholds,
            worker.model_ids,
            worker.fingerprint,
            worker.fusion_enabled,
        ) = old


def process_job(worker) -> bool:
    """Commit a claim before decoding so no transaction waits for inference."""
    worker.assert_owner()
    with worker.sessions.begin() as db:
        job = db.scalar(
            select(Job)
            .where(Job.state == "running", Job.worker_id == worker.worker_id)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            job = db.scalar(
                select(Job)
                .where(
                    or_(Job.state.in_(["queued", "paused"]), (Job.state == "running") & (Job.lease_until < utcnow()))
                )
                .order_by(Job.created_at)
                .with_for_update(skip_locked=True)
            )
        if job is None:
            return False
        if job.cancel_requested:
            job.state = "cancelled"
            return True
        job.state, job.worker_id = "running", worker.worker_id
        job.lease_until = utcnow() + timedelta(seconds=worker.config["worker_lease_seconds"])
        source = db.get(Source, job.source_id)
    started = time.perf_counter()
    try:
        with pinned(worker, job):
            source.enabled_models = list(job.snapshot["cards"])
            source.config = job.snapshot.get("source_config", source.config)
            if job.id not in worker.video_jobs:
                worker.video_jobs[job.id] = iter(frames(within(worker.media, job.path), job.snapshot["sample_fps"]))
            timestamp, rgb = next(worker.video_jobs[job.id])
            while timestamp <= job.cursor:
                timestamp, rgb = next(worker.video_jobs[job.id])
            worker.process(
                source,
                rgb,
                timestamp,
                job.captured_at + timedelta(seconds=timestamp) if job.captured_at else None,
                job.id,
            )
        worker.assert_owner()
        with worker.sessions.begin() as db:
            current = db.get(Job, job.id)
            current.cursor = max(current.cursor, timestamp)
            current.processed_frames += 1
            current.processing_seconds += time.perf_counter() - started
            if current.cancel_requested:
                current.state = "cancelled"
        return True
    except StopIteration:
        state, error = "completed", None
    except Exception as failure:
        state, error = "failed", f"{type(failure).__name__}: recording processing failed; inspect worker logs"
        import logging

        logging.getLogger(__name__).exception("Recording job failed")
    worker.assert_owner()
    with worker.sessions.begin() as db:
        current = db.get(Job, job.id)
        current.state, current.error = state, error
        current.processing_seconds += time.perf_counter() - started
    worker.video_jobs.pop(job.id, None)
    worker.release_finished_sessions()
    return True
