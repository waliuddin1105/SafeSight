import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, ShieldCheck, Check, X } from "lucide-react";
import { api } from "./api";
import { date } from "./time";
import { labels, slugs, type Incident, type Location } from "./types";
export interface Filters {
  type: string;
  location: string;
  status: string;
  from: string;
  to: string;
}
export function Incidents({
  items,
  locations,
  total,
  page,
  setPage,
  filters,
  setFilters,
  zone,
  refresh,
  onError,
}: {
  items: Incident[];
  locations: Location[];
  total: number;
  page: number;
  setPage: (page: number) => void;
  filters: Filters;
  setFilters: (filters: Filters) => void;
  zone: string;
  refresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [selected, setSelected] = useState<Incident | null>(null),
    [notes, setNotes] = useState("");
  const dialog = useRef<HTMLElement>(null),
    opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!selected) return;
    opener.current = document.activeElement as HTMLElement;
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
      if (event.key === "Tab") {
        const controls = Array.from(
          dialog.current?.querySelectorAll<HTMLElement>(
            "button,input,textarea,video[controls]",
          ) || [],
        );
        const first = controls[0],
          last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      opener.current?.focus();
    };
  }, [selected?.id]);
  async function open(id: string) {
    try {
      setSelected(await api<Incident>("/incidents/" + id));
      setNotes("");
    } catch (e) {
      onError((e as Error).message);
    }
  }
  async function review(decision: string) {
    if (!selected) return;
    try {
      await api("/incidents/" + selected.id + "/review", {
        method: "POST",
        body: JSON.stringify({ decision, notes }),
      });
      setSelected(await api<Incident>("/incidents/" + selected.id));
      await refresh();
    } catch (e) {
      onError((e as Error).message);
    }
  }
  return (
    <>
      <section id="incidents">
        <div className="section-head">
          <h2>Incident register</h2>
          <span>Evidence first. Review with context.</span>
        </div>
        <div className="filters">
          {(["type", "location", "status"] as const).map((k) => (
            <label key={k}>
              {k}
              <select
                aria-label={k + " filter"}
                value={filters[k]}
                onChange={(e) => {
                  setPage(1);
                  setFilters({ ...filters, [k]: e.target.value });
                }}
              >
                <option value="">All {k}</option>
                {(k === "type"
                  ? slugs.map((s) => [s, labels[s]])
                  : k === "location"
                    ? locations.map((l) => [l.id, l.name])
                    : ["pending", "confirmed", "dismissed"].map((s) => [s, s])
                ).map(([v, n]) => (
                  <option key={v} value={v}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {(["from", "to"] as const).map((k) => (
            <label key={k}>
              {k} ({zone})
              <input
                type="datetime-local"
                value={filters[k]}
                onChange={(e) => {
                  setPage(1);
                  setFilters({ ...filters, [k]: e.target.value });
                }}
              />
            </label>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Behavior / evidence</th>
                <th>Recorded</th>
                <th>Location</th>
                <th>Detection score</th>
                <th>Review</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <b>{labels[item.slug]}</b>
                    <small>
                      {item.subtype.replaceAll("_", " ")}
                      {item.uncertain ? " ? uncertain" : ""}
                      {item.evaluation_only ? " ? evaluation" : ""}
                    </small>
                  </td>
                  <td>
                    {date(item.start_at, zone)}
                    <small>Video +{item.start_offset.toFixed(1)}s</small>
                  </td>
                  <td>
                    {locations.find((l) => l.id === item.location_id)?.name ||
                      "Unknown location"}
                  </td>
                  <td>{Math.round(item.score * 100)}%</td>
                  <td>
                    <span className={"badge " + item.review_status}>
                      {item.review_status}
                    </span>
                  </td>
                  <td>
                    <button className="ghost" onClick={() => open(item.id)}>
                      Review <ArrowUpRight size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!items.length && (
            <div className="empty">
              <ShieldCheck size={32} />
              <h3>No incidents in this view</h3>
              <p>Adjust the filters or connect a source.</p>
            </div>
          )}
        </div>
        <div className="pagination">
          <button
            className="ghost"
            disabled={page === 1}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </button>
          <span>Page {page}</span>
          <button
            className="ghost"
            disabled={page * 25 >= total}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      </section>
      {selected && (
        <div className="modal-backdrop">
          <section
            ref={dialog}
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Incident review"
          >
            <button
              className="close ghost"
              onClick={() => setSelected(null)}
              aria-label="Close review"
            >
              <X />
            </button>
            <p className="eyebrow">INCIDENT EVIDENCE</p>
            <h2>{labels[selected.slug]}</h2>
            <p>
              {date(selected.start_at, zone)} ? {selected.review_status}
            </p>
            {selected.evaluation_only && (
              <p className="error">
                Evaluation artifact: this result is not qualified for
                production.
              </p>
            )}
            {!selected.evidence?.length && (
              <p>Evidence is unavailable for this incident.</p>
            )}
            {selected.evidence?.map((e) => (
              <div key={e.id}>
                {e.state === "ready" && e.url ? (
                  e.kind === "frame" ? (
                    <img src={e.url} alt="Incident evidence frame" />
                  ) : (
                    <video controls src={e.url} />
                  )
                ) : (
                  <p>
                    Evidence {e.state}
                    {e.error ? ": " + e.error : ""}
                  </p>
                )}
              </div>
            ))}
            <label>
              Review notes
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                maxLength={4000}
              />
            </label>
            <div className="actions">
              <button onClick={() => review("confirmed")}>
                <Check size={18} /> Confirm
              </button>
              <button className="ghost" onClick={() => review("dismissed")}>
                <X size={18} /> Dismiss
              </button>
            </div>
            <small>{selected.reviews?.length || 0} recorded reviews</small>
          </section>
        </div>
      )}
    </>
  );
}
