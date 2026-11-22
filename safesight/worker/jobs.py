"""Recording jobs with pinned artifacts, short claims and durable cancellation."""

from contextlib import contextmanager
from datetime import timedelta
import hashlib
from collections import deque
import logging
import time

from sqlalchemy import or_, select

from safesight.config import within
from safesight.ingestion.video import frames
from safesight.model_loaders.registry import Registry
from safesight.storage.schema import Job, Source, ModelVersion, RuntimeSnapshot, utcnow
from safesight.inference.state import loads


class ChunkCommitError(RuntimeError):
    """Committed state was restored and the recording may be replayed."""


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
            chunk = []
            iterator = worker.video_jobs[job.id]
            while len(chunk) < worker.config.get("upload_batch_size", 8):
                frame = next(iterator, None)
                if frame is None:
                    break
                if frame[0] > job.cursor:
                    chunk.append(frame)
            if not chunk:
                raise StopIteration
            prepared = [{"people": [], "predictions": {}} for _ in chunk]
            images = [rgb for _, rgb in chunk]
            timestamps = [timestamp for timestamp, _ in chunk]
            from safesight.worker.__main__ import needs_pose_context

            if worker.registry.pose and needs_pose_context(source.enabled_models, worker.registry.adapters):
                for index, rgb in enumerate(images):
                    prepared[index]["people"] = worker.registry.pose.extract(rgb)
            for slug in source.enabled_models:
                adapter = worker.registry.adapters.get(slug)
                if adapter is None:
                    continue
                try:
                    if hasattr(adapter, "predict_batch"):
                        try:
                            predictions = adapter.predict_batch(images, timestamps)
                        except RuntimeError as error:
                            if "out of memory" not in str(error).lower() or len(chunk) == 1:
                                raise
                            import torch

                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                            logging.getLogger(__name__).warning(
                                "Batch inference exhausted GPU memory for %s; retrying one frame at a time", slug
                            )
                            predictions = [adapter.predict(rgb, timestamp) for timestamp, rgb in chunk]
                    else:
                        predictions = []
                        for (timestamp, rgb), context in zip(chunk, prepared):
                            if hasattr(adapter, "buffer"):
                                key = f"{source.id}:{source.generation}:{job.id}"
                                adapter.buffer = worker.adapter_buffers.setdefault(
                                    (key, slug), deque(maxlen=adapter.card.sequence_length)
                                )
                                adapter.source_config = source.config
                            if slug == "body_state":
                                predictions.append(adapter.predict(rgb, timestamp, people=context["people"]))
                            else:
                                predictions.append(adapter.predict(rgb, timestamp))
                    if len(predictions) != len(chunk):
                        raise ValueError(f"{slug} returned an incorrect batch length")
                    for record, prediction in zip(prepared, predictions):
                        record["predictions"][slug] = prediction
                except (RuntimeError, ValueError) as error:
                    logging.getLogger(__name__).exception("Inference failed for %s", slug)
                    worker.registry.status[slug] = {"ready": False, "reason": str(error)}
            worker.assert_owner()
            cancelled = False
            try:
                with worker.sessions.begin() as db:
                    current = db.get(Job, job.id)
                    if current.cancel_requested:
                        current.state = "cancelled"
                        cancelled = True
                    else:
                        for (timestamp, rgb), context in zip(chunk, prepared):
                            worker.process(
                                source, rgb, timestamp,
                                job.captured_at + timedelta(seconds=timestamp) if job.captured_at else None,
                                job.id, db=db, prepared=context,
                            )
                        key = f"{source.id}:{source.generation}:{job.id}"
                        worker.checkpoint(db, key)
                        current.cursor = max(current.cursor, chunk[-1][0])
                        current.processed_frames += len(chunk)
                        current.processing_seconds += time.perf_counter() - started
                        current.lease_until = utcnow() + timedelta(seconds=worker.config["worker_lease_seconds"])
            except Exception as failure:
                key = f"{source.id}:{source.generation}:{job.id}"
                with worker.sessions() as db:
                    snapshot = db.get(RuntimeSnapshot, key)
                    state = loads(snapshot.payload, worker.get_blob) if snapshot else None
                if state:
                    worker.engines[key], worker.buffers[key] = state["engine"], state["buffer"]
                else:
                    worker.engines.pop(key, None)
                    worker.buffers.pop(key, None)
                worker.adapter_buffers = {k: v for k, v in worker.adapter_buffers.items() if k[0] != key}
                worker.pending = {k: v for k, v in worker.pending.items() if v[0] != key}
                if state:
                    worker.adapter_buffers.update(state["adapters"])
                    worker.pending.update(state["pending"])
                for slug in source.enabled_models:
                    adapter = worker.registry.adapters.get(slug)
                    if adapter is not None and hasattr(adapter, "buffer"):
                        adapter.buffer = worker.adapter_buffers.get(
                            (key, slug), deque(maxlen=adapter.card.sequence_length)
                        )
                        if hasattr(adapter, "frames_seen"):
                            adapter.frames_seen = len(adapter.buffer)
                worker.video_jobs.pop(job.id, None)
                raise ChunkCommitError("Chunk transaction failed; replaying from committed cursor") from failure
            if not cancelled:
                worker.flush_clips(chunk[-1][0], key)
            worker.job_retries.pop(job.id, None)
        return True
    except StopIteration:
        state, error = "completed", None
    except ChunkCommitError as failure:
        retries = worker.job_retries.get(job.id, 0) + 1
        worker.job_retries[job.id] = retries
        state = "paused" if retries < 3 else "failed"
        error = str(failure)
    except Exception as failure:
        state, error = "failed", f"{type(failure).__name__}: recording processing failed; inspect worker logs"
        logging.getLogger(__name__).exception("Recording job failed")
    worker.assert_owner()
    with worker.sessions.begin() as db:
        current = db.get(Job, job.id)
        current.state, current.error = state, error
        current.processing_seconds += time.perf_counter() - started
    worker.video_jobs.pop(job.id, None)
    worker.release_finished_sessions()
    return True
