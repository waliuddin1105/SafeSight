import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Activity,
  Camera,
  CheckCircle2,
  Clock3,
  Image as ImageIcon,
  ShieldAlert,
  Upload,
  Video,
} from "lucide-react";
import { api } from "./api";
import type { CaptureController } from "./capture";
import { date, localTimeToIso } from "./time";
import {
  labels,
  slugs,
  type Source,
  type Slug,
  type Job,
  type JobFrame,
  type ModelVersion,
  type ModelStatus,
  type ListResponse,
  type Incident,
} from "./types";

type TestMode = "video" | "webcam" | "image";

const modes: Array<{
  id: TestMode;
  title: string;
  detail: string;
  icon: typeof Video;
  index: string;
}> = [
  {
    id: "video",
    title: "Recorded footage",
    detail:
      "Replay a complete shift clip with a pinned model version and alert timeline.",
    icon: Video,
    index: "01",
  },
  {
    id: "webcam",
    title: "Live webcam",
    detail:
      "Evaluate the active models against a browser camera with visible capture health.",
    icon: Camera,
    index: "02",
  },
  {
    id: "image",
    title: "Still image",
    detail:
      "Inspect object and posture predictions on one image without claiming temporal alerts.",
    icon: ImageIcon,
    index: "03",
  },
];

export function TestingWorkspace({
  sources,
  zone,
  models,
  capture,
}: {
  sources: Source[];
  zone: string;
  models: Record<string, ModelStatus>;
  capture: CaptureController;
}) {
  const [mode, setMode] = useState<TestMode>("video"),
    [jobs, setJobs] = useState<Job[]>([]),
    [job, setJob] = useState<Job | null>(null),
    [versions, setVersions] = useState<ModelVersion[]>([]),
    [selected, setSelected] = useState<Slug[]>([]),
    [webcamModels, setWebcamModels] = useState<Slug[]>([]),
    [chosen, setChosen] = useState<Partial<Record<Slug, string>>>({}),
    [evaluation, setEvaluation] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [frames, setFrames] = useState<JobFrame[]>([]),
    [alerts, setAlerts] = useState<Incident[]>([]),
    [position, setPosition] = useState(0),
    [metrics, setMetrics] = useState<{
      available: boolean;
      precision?: number | null;
      recall?: number | null;
      reason?: string;
    } | null>(null);
  const player = useRef<HTMLVideoElement>(null),
    [ratio, setRatio] = useState(16 / 9),
    epoch = useRef(0),
    cursor = useRef(-1);

  const availableWebcamModels = slugs.filter((slug) => models[slug]?.ready);
  const chosenVersions = selected
    .map((slug) =>
      versions.find(
        (version) => version.slug === slug && version.run_id === chosen[slug],
      ),
    )
    .filter((version): version is ModelVersion => Boolean(version));
  const requiresEvaluation = chosenVersions.some(
    (version) => version.synthetic || version.quality.status !== "PASS",
  );

  useEffect(() => {
    if (requiresEvaluation) setEvaluation(true);
  }, [requiresEvaluation]);
  useEffect(() => {
    if (mode === "image" && selected.includes("entrance_guard")) {
      setSelected((current) =>
        current.filter((slug) => slug !== "entrance_guard"),
      );
    }
  }, [mode, selected]);
  useEffect(() => {
    if (!webcamModels.length && availableWebcamModels.length) {
      setWebcamModels(availableWebcamModels);
    }
  }, [availableWebcamModels.join("|")]);
  useEffect(() => {
    const controller = new AbortController();
    api<{ items: ModelVersion[] }>("/models/versions", {
      signal: controller.signal,
    })
      .then((response) => setVersions(response.items))
      .catch((reason) => {
        if (reason.name !== "AbortError") setError(reason.message);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        setJobs(
          (await api<ListResponse<Job>>("/jobs", { signal: controller.signal }))
            .items,
        );
      } catch (reason) {
        if ((reason as Error).name !== "AbortError")
          setError((reason as Error).message);
      } finally {
        pending = false;
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!job?.id) return;
    const id = job.id,
      controller = new AbortController(),
      current = ++epoch.current;
    let pending = false;
    cursor.current = -1;
    setFrames([]);
    setAlerts([]);
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const [detail, predictions, incidents, measured] = await Promise.all([
          api<Job>("/jobs/" + id, { signal: controller.signal }),
          api<{ items: JobFrame[]; next_after: number | null }>(
            "/jobs/" + id + "/predictions?after=" + cursor.current,
            { signal: controller.signal },
          ),
          api<{ items: Incident[] }>("/jobs/" + id + "/incidents", {
            signal: controller.signal,
          }),
          api<{
            available: boolean;
            precision?: number | null;
            recall?: number | null;
            reason?: string;
          }>("/jobs/" + id + "/metrics", { signal: controller.signal }),
        ]);
        if (current !== epoch.current) return;
        setJob(detail);
        setAlerts(incidents.items);
        setMetrics(measured);
        if (predictions.items.length) {
          setFrames((old) => [...old, ...predictions.items].slice(-5000));
          cursor.current = predictions.next_after ?? cursor.current;
        }
      } catch (reason) {
        if ((reason as Error).name !== "AbortError")
          setError((reason as Error).message);
      } finally {
        pending = false;
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      epoch.current++;
      controller.abort();
      clearInterval(timer);
    };
  }, [job?.id]);

  function toggleModel(slug: Slug, enabled: boolean) {
    if (!enabled) {
      setSelected((current) => current.filter((item) => item !== slug));
      return;
    }
    const first = versions.find((version) => version.slug === slug);
    if (!first) return;
    setSelected((current) => [...current, slug]);
    setChosen((current) => ({ ...current, [slug]: first.run_id }));
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    form.set("models", JSON.stringify(selected));
    form.set("versions", JSON.stringify(chosen));
    form.set("evaluation", String(evaluation));
    const captureTime = String(form.get("captured_at") || "");
    try {
      if (captureTime)
        form.set("captured_at", localTimeToIso(captureTime, zone));
      else form.delete("captured_at");
      setBusy(true);
      setError("");
      const uploaded = await api<Job>("/uploads", {
        method: "POST",
        body: form,
      });
      setJob(uploaded);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function seek(timestamp: number) {
    if (player.current) {
      player.current.currentTime = timestamp;
      setPosition(timestamp);
    }
  }
  const visible = useMemo(
    () =>
      [...frames]
        .reverse()
        .find(
          (frame) =>
            frame.timestamp <= position && position - frame.timestamp < 1,
        ),
    [frames, position],
  );

  return (
    <section className="testing-page" aria-labelledby="testing-title">
      <div className="testing-hero">
        <div>
          <p className="eyebrow">MODEL TESTING LAB / CONTROLLED INPUT</p>
          <h1 id="testing-title">
            Choose the evidence.
            <br />
            <em>See what the model sees.</em>
          </h1>
          <p className="testing-lead">
            Run isolated evaluations without changing globally active models.
            Scores are model confidence, not measured accuracy.
          </p>
        </div>
        <div className="lab-status" aria-label="Testing system status">
          <span>{versions.length}</span>
          <small>installed model versions</small>
          <span>{availableWebcamModels.length}</span>
          <small>active for live testing</small>
        </div>
      </div>

      <div className="mode-grid" aria-label="Choose testing input">
        {modes.map((item) => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              key={item.id}
              className={"mode-card" + (mode === item.id ? " selected" : "")}
              aria-pressed={mode === item.id}
              onClick={() => {
                setMode(item.id);
                setError("");
              }}
            >
              <span className="mode-index">{item.index}</span>
              <Icon size={26} />
              <strong>{item.title}</strong>
              <small>{item.detail}</small>
              {mode === item.id && (
                <CheckCircle2 className="mode-check" size={18} />
              )}
            </button>
          );
        })}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {mode === "webcam" ? (
        <section
          className="lab-panel webcam-panel"
          aria-label="Webcam evaluation"
        >
          <div className="lab-panel-copy">
            <p className="eyebrow">LIVE / ACTIVE VERSIONS</p>
            <h2>Configure the live observation</h2>
            <p>
              Browser frames are sampled at 5 FPS and processed by the worker.
              Stop capture before leaving this page.
            </p>
            <label>
              Browser camera source
              <select
                value={capture.sourceId}
                disabled={capture.live}
                onChange={(event) => capture.setSourceId(event.target.value)}
              >
                <option value="">Select a configured browser source</option>
                {sources
                  .filter((source) => source.kind === "browser")
                  .map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name}
                    </option>
                  ))}
              </select>
            </label>
            <fieldset className="model-picker compact">
              <legend>Models to evaluate</legend>
              {slugs.map((slug) => {
                const ready = models[slug]?.ready;
                return (
                  <label
                    className={"model-option" + (!ready ? " unavailable" : "")}
                    key={slug}
                  >
                    <input
                      type="checkbox"
                      disabled={!ready || capture.live}
                      checked={webcamModels.includes(slug)}
                      onChange={(event) =>
                        setWebcamModels((current) =>
                          event.target.checked
                            ? [...current, slug]
                            : current.filter((item) => item !== slug),
                        )
                      }
                    />
                    <span>
                      <strong>{labels[slug]}</strong>
                      <small>
                        {ready
                          ? models[slug]?.evaluation_only
                            ? "Evaluation only"
                            : "Ready"
                          : "No active model"}
                      </small>
                    </span>
                  </label>
                );
              })}
            </fieldset>
            <button
              disabled={
                !capture.live && (!capture.sourceId || !webcamModels.length)
              }
              onClick={async () => {
                try {
                  setError("");
                  if (capture.live) await capture.stop();
                  else await capture.start(webcamModels);
                } catch (reason) {
                  setError((reason as Error).message);
                }
              }}
            >
              {capture.live ? "Stop webcam test" : "Start webcam test"}
              <Camera size={17} />
            </button>
          </div>
          <div className="camera-stage">
            <video
              ref={capture.video}
              muted
              playsInline
              aria-label="Live testing camera preview"
            />
            <div className="camera-hud">
              <span className={capture.live ? "live" : ""}>
                {capture.live ? "LIVE" : "STANDBY"}
              </span>
              <span>
                {webcamModels.length} model
                {webcamModels.length === 1 ? "" : "s"}
              </span>
            </div>
            {!capture.live && (
              <p>Camera preview appears here after permission is granted.</p>
            )}
          </div>
        </section>
      ) : (
        <section
          className="lab-panel upload-panel"
          aria-label={`${mode} evaluation`}
        >
          <form onSubmit={upload}>
            <div className="lab-panel-heading">
              <div>
                <p className="eyebrow">
                  {mode === "image" ? "SINGLE FRAME" : "RECORDED SEQUENCE"}
                </p>
                <h2>
                  {mode === "image"
                    ? "Inspect an image"
                    : "Replay recorded footage"}
                </h2>
              </div>
              {mode === "image" ? <ImageIcon /> : <Upload />}
            </div>
            <div className="form-grid">
              <label>
                Testing location/source
                <select name="source_id" required>
                  <option value="">Select upload source</option>
                  {sources
                    .filter((source) => source.kind === "upload")
                    .map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                {mode === "image" ? "Image" : "Video recording"}
                <input
                  key={mode}
                  name="file"
                  type="file"
                  accept={
                    mode === "image"
                      ? "image/jpeg,image/png,image/webp"
                      : "video/*,.mkv"
                  }
                  required
                />
              </label>
              <label>
                Captured at ({zone}, optional)
                <input type="datetime-local" name="captured_at" />
              </label>
              {mode === "video" && (
                <label>
                  Optional event ground truth (JSON)
                  <textarea name="ground_truth" placeholder='{"events":[]}' />
                </label>
              )}
            </div>

            <fieldset className="model-picker">
              <legend>Choose models and exact versions</legend>
              <div className="model-picker-grid">
                {slugs.map((slug) => {
                  const available = versions.filter(
                    (version) => version.slug === slug,
                  );
                  const unsupported =
                    mode === "image" && slug === "entrance_guard";
                  return (
                    <div
                      className={
                        "model-option" +
                        (!available.length || unsupported ? " unavailable" : "")
                      }
                      key={slug}
                    >
                      <label>
                        <input
                          type="checkbox"
                          checked={selected.includes(slug)}
                          disabled={!available.length || unsupported}
                          onChange={(event) =>
                            toggleModel(slug, event.target.checked)
                          }
                        />
                        <span>
                          <strong>{labels[slug]}</strong>
                          <small>
                            {unsupported
                              ? "Requires an ordered sequence"
                              : available.length
                                ? `${available.length} version${available.length === 1 ? "" : "s"}`
                                : "No installed version"}
                          </small>
                        </span>
                      </label>
                      {selected.includes(slug) && (
                        <select
                          aria-label={labels[slug] + " version"}
                          value={chosen[slug] || ""}
                          onChange={(event) =>
                            setChosen({ ...chosen, [slug]: event.target.value })
                          }
                        >
                          {available.map((version) => (
                            <option key={version.run_id} value={version.run_id}>
                              {version.run_id} ·{" "}
                              {version.synthetic
                                ? "synthetic"
                                : version.quality.status}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  );
                })}
              </div>
            </fieldset>

            <div className="submission-bar">
              <label className="evaluation-consent">
                <input
                  type="checkbox"
                  checked={evaluation}
                  disabled={requiresEvaluation}
                  onChange={(event) => setEvaluation(event.target.checked)}
                />
                <span>
                  <strong>Evaluation mode</strong>
                  <small>
                    {requiresEvaluation
                      ? "Required by the selected unqualified version"
                      : "Allow evaluation-only artifacts"}
                  </small>
                </span>
              </label>
              <button
                disabled={
                  busy ||
                  !selected.length ||
                  selected.some((slug) => !chosen[slug])
                }
              >
                {busy
                  ? "Preparing test…"
                  : mode === "image"
                    ? "Evaluate image"
                    : "Queue footage"}
                {mode === "image" ? (
                  <ImageIcon size={17} />
                ) : (
                  <Upload size={17} />
                )}
              </button>
            </div>
          </form>
        </section>
      )}

      {mode !== "webcam" && (
        <section className="job-console">
          <div className="job-rail">
            <div className="section-head">
              <h2>
                <Clock3 size={18} /> Test history
              </h2>
              <span>{jobs.length} RECENT</span>
            </div>
            {!jobs.length && (
              <p className="muted">No tests have been queued yet.</p>
            )}
            <ul className="job-history">
              {jobs.map((item) => (
                <li key={item.id}>
                  <button
                    className={
                      "ghost " + (job?.id === item.id ? "selected" : "")
                    }
                    onClick={() => setJob(item)}
                  >
                    <span>
                      {item.snapshot.media_kind === "image" ? (
                        <ImageIcon size={15} />
                      ) : (
                        <Video size={15} />
                      )}{" "}
                      {item.snapshot.original_filename ||
                        date(item.created_at, zone)}
                    </span>
                    <small>
                      {item.state} · {item.processed_frames} observations
                    </small>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {job ? (
            <article className="test-result">
              <div className="section-head">
                <div>
                  <p className="eyebrow">
                    PINNED TEST / {job.snapshot.media_kind || "VIDEO"}
                  </p>
                  <h2>
                    <Activity size={18} /> {job.state}
                  </h2>
                </div>
                {!["completed", "failed", "cancelled"].includes(job.state) && (
                  <button
                    className="ghost"
                    disabled={job.cancel_requested}
                    onClick={async () => {
                      try {
                        setJob(
                          await api<Job>("/jobs/" + job.id + "/cancel", {
                            method: "POST",
                          }),
                        );
                      } catch (reason) {
                        setError((reason as Error).message);
                      }
                    }}
                  >
                    {job.cancel_requested ? "Cancelling…" : "Cancel test"}
                  </button>
                )}
              </div>
              <progress
                aria-label="Processing progress"
                value={Math.max(0, job.cursor)}
                max={job.duration || 1}
              />
              <div className="result-meta">
                <span>
                  {job.processed_frames} sampled frame
                  {job.processed_frames === 1 ? "" : "s"}
                </span>
                <span>
                  {job.processing_seconds
                    ? (job.processed_frames / job.processing_seconds).toFixed(1)
                    : "—"}{" "}
                  processing FPS
                </span>
              </div>
              {job.error && <p className="error">{job.error}</p>}
              {job.snapshot.evaluation && (
                <p className="evaluation-banner">
                  <ShieldAlert size={18} /> Evaluation-only results are not
                  production-qualified.
                </p>
              )}
              <div className="video-stage" style={{ aspectRatio: ratio }}>
                <video
                  key={job.id}
                  ref={player}
                  src={"/api/v1/jobs/" + job.id + "/video"}
                  controls
                  onTimeUpdate={(event) =>
                    setPosition(event.currentTarget.currentTime)
                  }
                  onLoadedMetadata={(event) =>
                    setRatio(
                      event.currentTarget.videoWidth /
                        event.currentTarget.videoHeight || 16 / 9,
                    )
                  }
                />
                <svg
                  viewBox="0 0 1000 1000"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  {visible?.predictions.flatMap((prediction) =>
                    prediction.detections.map((detection, index) => (
                      <rect
                        key={prediction.slug + index}
                        x={detection.box[0] * 1000}
                        y={detection.box[1] * 1000}
                        width={(detection.box[2] - detection.box[0]) * 1000}
                        height={(detection.box[3] - detection.box[1]) * 1000}
                      />
                    )),
                  )}
                </svg>
              </div>
              <div className="prediction-readout">
                <small>{position.toFixed(1)} SECONDS</small>
                {visible?.predictions.length ? (
                  visible.predictions.map((prediction) => (
                    <p key={prediction.slug}>
                      <b>{labels[prediction.slug]}</b>
                      {prediction.unknown_reason ||
                        prediction.detections
                          .map(
                            (detection) =>
                              `${detection.label} ${(detection.score * 100).toFixed(0)}%`,
                          )
                          .join(", ") ||
                        "No detections"}
                    </p>
                  ))
                ) : (
                  <p>No sampled result at this position yet.</p>
                )}
              </div>
              <p className="muted">
                {metrics?.available
                  ? `Ground-truth event precision: ${metrics.precision == null ? "undefined" : (metrics.precision * 100).toFixed(1) + "%"}; recall: ${metrics.recall == null ? "undefined" : (metrics.recall * 100).toFixed(1) + "%"}.`
                  : metrics?.reason || "No ground-truth metrics available."}
              </p>
              <h3>Alert timeline</h3>
              {!alerts.length && (
                <p className="muted">
                  No alerts emitted. This does not establish that the input is
                  safe.
                </p>
              )}
              <div className="timeline">
                {alerts.map((alert) => (
                  <button
                    className="ghost"
                    key={alert.id}
                    onClick={() => seek(alert.start_offset)}
                  >
                    {labels[alert.slug]} · {alert.start_offset.toFixed(1)}–
                    {alert.end_offset.toFixed(1)}s
                  </button>
                ))}
              </div>
              <details>
                <summary>Sampled observations and unknown periods</summary>
                <div className="observations">
                  {frames.map((frame) => (
                    <button
                      className="ghost"
                      key={frame.timestamp}
                      onClick={() => seek(frame.timestamp)}
                    >
                      {frame.timestamp.toFixed(1)}s ·{" "}
                      {Object.values(frame.unknown).join("; ") ||
                        frame.predictions
                          .map(
                            (prediction) =>
                              prediction.unknown_reason ||
                              `${labels[prediction.slug]}: ${prediction.detections.length} detections`,
                          )
                          .join("; ")}
                    </button>
                  ))}
                </div>
              </details>
            </article>
          ) : (
            <div className="result-empty">
              <Activity size={28} />
              <h2>Results will appear here</h2>
              <p>Choose an input and model version, then start a test.</p>
            </div>
          )}
        </section>
      )}
    </section>
  );
}
