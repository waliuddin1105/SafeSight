import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ShieldCheck,
  Radio,
  ArrowUpRight,
  X,
  Camera,
  Menu,
} from "lucide-react";
import { api, setCsrf } from "./api";
import { Authentication } from "./Authentication";
import { useCapture } from "./capture";
import { Incidents, type Filters } from "./Incidents";
import { TestingWorkspace } from "./TestingWorkspace";
import { WorkspaceSetup } from "./WorkspaceSetup";
import { localTimeToIso } from "./time";
import {
  labels,
  slugs,
  type User,
  type Source,
  type Location,
  type ModelStatus,
  type Incident,
  type AuthResponse,
  type OverviewResponse,
} from "./types";
import "./style.css";
function App() {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [zone, setZone] = useState("Asia/Karachi");
  const [sources, setSources] = useState<Source[]>([]),
    [locations, setLocations] = useState<Location[]>([]),
    [models, setModels] = useState<Record<string, ModelStatus>>({}),
    [items, setItems] = useState<Incident[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(1),
    [worker, setWorker] = useState(false);
  const [filters, setFilters] = useState<Filters>({
    type: "",
    location: "",
    status: "",
    from: "",
    to: "",
  });
  const capture = useCapture(sources, setError),
    generation = useRef(0);
  const [navOpen, setNavOpen] = useState(false);
  const [view, setView] = useState<"overview" | "testing">("overview");
  useEffect(() => {
    if (!navOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [navOpen]);

  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener("auth-expired", expired);
    const abort = new AbortController();
    api<AuthResponse>("/auth/me", { signal: abort.signal })
      .then((d) => {
        setCsrf(d.csrf_token);
        setUser(d.user);
        setZone(d.timezone || "Asia/Karachi");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => {
      abort.abort();
      window.removeEventListener("auth-expired", expired);
    };
  }, []);
  const refresh = useCallback(async () => {
    const current = ++generation.current;
    const params = new URLSearchParams({ page: String(page) });
    Object.entries(filters).forEach(([k, v]) => {
      if (v)
        params.set(k, k === "from" || k === "to" ? localTimeToIso(v, zone) : v);
    });
    const response = await api<OverviewResponse>("/overview?" + params);
    if (current !== generation.current) return;
    setSources(response.sources);
    setLocations(response.locations);
    setModels(response.models.items);
    setWorker(response.models.worker_alive);
    setItems(response.incidents.items);
    setTotal(response.incidents.total);
  }, [page, filters, zone]);
  useEffect(() => {
    if (!user || view !== "overview") return;
    let active = true,
      pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        await refresh();
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        pending = false;
      }
    };
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      active = false;
      generation.current++;
      clearInterval(timer);
    };
  }, [user, refresh, view]);
  async function run(action: () => Promise<void>) {
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function navigate(next: "overview" | "testing") {
    if (view === "testing" && next !== view && capture.live) {
      await run(capture.stop);
    }
    setView(next);
    setNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  if (loading)
    return (
      <main className="signin">
        <ShieldCheck />
        <p>Connecting to SafeSight?</p>
      </main>
    );
  if (!user)
    return (
      <Authentication
        initialError={error}
        onLogin={(account) => {
          setError("");
          setUser(account);
        }}
      />
    );
  return (
    <div className="shell">
      <aside>
        <div className="aside-top">
          <div className="brand">
            <ShieldCheck />
            SafeSight
          </div>
          <button
            type="button"
            className="ghost nav-toggle"
            aria-label={navOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={navOpen}
            aria-controls="aside-panel"
            onClick={() => setNavOpen((open) => !open)}
          >
            {navOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        <div
          id="aside-panel"
          className={"aside-panel" + (navOpen ? " open" : "")}
        >
          <small>SAFETY OPERATIONS / 01</small>
          <nav className="nav-links" aria-label="Primary">
            <button
              type="button"
              className={"nav" + (view === "overview" ? " active" : "")}
              aria-current={view === "overview" ? "page" : undefined}
              onClick={() => navigate("overview")}
            >
              Safety overview <ArrowUpRight size={16} />
            </button>
            <button
              type="button"
              className={"nav" + (view === "testing" ? " active" : "")}
              aria-current={view === "testing" ? "page" : undefined}
              onClick={() => navigate("testing")}
            >
              Testing lab <Camera size={16} />
            </button>
          </nav>
          <div className="aside-bottom">
            <small>
              {user.username} ? {user.role}
            </small>
            <button
              className="ghost"
              onClick={() => {
                setNavOpen(false);
                run(async () => {
                  if (capture.live) await capture.stop();
                  await api("/auth/logout", { method: "POST" });
                  setUser(null);
                  const d = await api<AuthResponse>("/auth/me");
                  setCsrf(d.csrf_token);
                });
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main>
        <header>
          <span>
            <i />
            SAFESIGHT / MONITOR & REVIEW
          </span>
          <span>{zone}</span>
        </header>
        {view === "overview" ? (
          <>
            <section className="intro">
              <div>
                <p className="eyebrow">YOUR SAFETY DESK</p>
                <h1>
                  See what needs
                  <br />
                  <em>your attention.</em>
                </h1>
              </div>
              <div className="count">
                <strong>{String(total).padStart(2, "0")}</strong>
                <span>
                  incidents matching
                  <br />
                  your filters
                </span>
              </div>
            </section>
            {error && (
              <div role="alert" className="error">
                {error}
                <button onClick={() => setError("")} aria-label="Dismiss error">
                  <X />
                </button>
              </div>
            )}
            {!worker && (
              <p className="error" role="status">
                Inference worker is offline. Captured frames cannot be analyzed
                until it reconnects.
              </p>
            )}
            {worker && models.fusion && !models.fusion.ready && (
              <p>
                Smoke-source fusion awaits joint validation. Unresolved smoke
                remains reviewable.
              </p>
            )}
            <section className="health" aria-label="Model readiness">
              {slugs.map((slug) => (
                <div key={slug}>
                  <span
                    className={"dot " + (models[slug]?.ready ? "ok" : "")}
                  />
                  <span>
                    {labels[slug]}
                    <small>
                      {models[slug]?.ready
                        ? models[slug]?.evaluation_only
                          ? "Evaluation only"
                          : "Ready"
                        : "Unavailable"}
                    </small>
                    {models[slug]?.reason && (
                      <small>{models[slug].reason}</small>
                    )}
                  </span>
                </div>
              ))}
            </section>
            <Incidents
              items={items}
              locations={locations}
              total={total}
              page={page}
              setPage={setPage}
              filters={filters}
              setFilters={setFilters}
              zone={zone}
              refresh={refresh}
              onError={setError}
            />
            <section className="capture-grid" id="capture">
              <article>
                <div className="section-head">
                  <h2>
                    <Camera size={20} /> Live source
                  </h2>
                  <span>{capture.live ? "CAPTURING" : "STANDBY"}</span>
                </div>
                <video
                  ref={capture.video}
                  muted
                  playsInline
                  aria-label="Local camera preview"
                />
                <select
                  aria-label="Live source"
                  disabled={capture.live}
                  value={capture.sourceId}
                  onChange={(e) => capture.setSourceId(e.target.value)}
                >
                  <option value="">Select camera source</option>
                  {sources
                    .filter((s) => s.kind !== "upload")
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                </select>
                <button
                  onClick={() =>
                    run(capture.live ? capture.stop : capture.start)
                  }
                >
                  {capture.live ? "Stop capture" : "Start capture"}{" "}
                  <Radio size={17} />
                </button>
                <p className="muted">
                  Camera permission is requested when you start. Audio is
                  disabled.
                </p>
                {sources
                  .filter((s) => s.active)
                  .map((s) => (
                    <p key={s.id}>
                      {s.name}: {s.health.status} ?{" "}
                      {s.health.dropped_frames || 0} dropped frames
                    </p>
                  ))}
              </article>
            </section>
            {user.role === "admin" && (
              <WorkspaceSetup
                zone={zone}
                locations={locations}
                refresh={refresh}
                onError={setError}
              />
            )}
          </>
        ) : (
          <TestingWorkspace
            sources={sources}
            zone={zone}
            models={models}
            capture={capture}
          />
        )}
        <footer>
          SAFESIGHT <span>AI observations require human review.</span>
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
