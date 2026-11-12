import { useState, type FormEvent } from "react";
import { api } from "./api";
import { slugs, labels, type Location, type Slug } from "./types";
export function WorkspaceSetup({
  locations,
  refresh,
  onError,
  zone,
}: {
  zone: string;
  locations: Location[];
  refresh: () => Promise<void>;
  onError: (error: string) => void;
}) {
  const [kind, setKind] = useState("browser"),
    [models, setModels] = useState<Slug[]>(slugs),
    [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>, location: boolean) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      if (location) {
        const policies = JSON.parse(String(form.get("policies") || "{}"));
        await api("/locations", {
          method: "POST",
          body: JSON.stringify({
            name: form.get("name"),
            timezone: form.get("timezone"),
            policies,
          }),
        });
      } else {
        const config: Record<string, unknown> = {};
        if (kind === "rtsp") config.uri = form.get("uri");
        if (kind === "usb") config.device = Number(form.get("device"));
        config.entrance_roi = JSON.parse(String(form.get("entrance_roi")));
        config.guard_region = JSON.parse(String(form.get("guard_region")));
        config.crossing_line_y = Number(form.get("crossing_line_y"));
        await api("/sources", {
          method: "POST",
          body: JSON.stringify({
            name: form.get("name"),
            location_id: form.get("location_id"),
            kind,
            enabled_models: models,
            config,
          }),
        });
      }
      await refresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="setup">
      <h2>Workspace setup</h2>
      <form onSubmit={(e) => submit(e, true)}>
        <label>
          New location
          <input name="name" required maxLength={120} />
        </label>
        <label>
          Timezone
          <input name="timezone" defaultValue={zone} required />
        </label>
        <label>
          Location policies (JSON)
          <textarea name="policies" defaultValue="{}" />
        </label>
        <button disabled={busy}>Add location</button>
      </form>
      <form onSubmit={(e) => submit(e, false)}>
        <label>
          Source name
          <input name="name" required maxLength={120} />
        </label>
        <label>
          Location
          <select name="location_id" required>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Input
          <select
            name="kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="browser">Browser camera</option>
            <option value="upload">Recording upload</option>
            <option value="usb">Server USB camera</option>
            <option value="rtsp">RTSP camera</option>
          </select>
        </label>
        {kind === "rtsp" && (
          <label>
            RTSP URL
            <input
              name="uri"
              type="url"
              required
              placeholder="rtsp://camera/stream"
            />
            <small>
              The backend configuration must allow this camera host.
            </small>
          </label>
        )}
        {kind === "usb" && (
          <label>
            USB device index
            <input
              name="device"
              type="number"
              min="0"
              defaultValue="0"
              required
            />
          </label>
        )}
        <fieldset>
          <legend>Enabled models</legend>
          {slugs.map((s) => (
            <label key={s}>
              <input
                type="checkbox"
                checked={models.includes(s)}
                onChange={(e) =>
                  setModels(
                    e.target.checked
                      ? [...models, s]
                      : models.filter((v) => v !== s),
                  )
                }
              />
              {labels[s]}
            </label>
          ))}
        </fieldset>
        <label>
          Entrance region [x1,y1,x2,y2]
          <input name="entrance_roi" defaultValue="[0,0,1,1]" required />
        </label>
        <label>
          Guard region [x1,y1,x2,y2]
          <input name="guard_region" defaultValue="[0,0,1,1]" required />
        </label>
        <label>
          Crossing line Y
          <input
            name="crossing_line_y"
            type="number"
            min="0.01"
            max="0.99"
            step="0.01"
            defaultValue="0.75"
          />
        </label>
        <button disabled={busy || !models.length}>Add source</button>
      </form>
    </section>
  );
}
