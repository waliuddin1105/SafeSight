export function date(value: string | null, zone: string) {
  return value
    ? new Date(value).toLocaleString("en-GB", {
        timeZone: zone,
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Capture time unknown";
}
export function localTimeToIso(value: string, zone: string): string {
  const desired = new Date(value + "Z").getTime();
  if (!Number.isFinite(desired)) throw new Error("Invalid date");
  const parts = (t: number) =>
    Object.fromEntries(
      new Intl.DateTimeFormat("en-CA", {
        timeZone: zone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(new Date(t))
        .map((p) => [p.type, p.value]),
    );
  let time = desired;
  for (let i = 0; i < 3; i++) {
    const p = parts(time);
    const seen = Date.UTC(
      +p.year,
      +p.month - 1,
      +p.day,
      +p.hour,
      +p.minute,
      +p.second,
    );
    time += desired - seen;
  }
  const p = parts(time);
  if (`${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}` !== value)
    throw new Error("Date does not exist in the selected timezone");
  return new Date(time).toISOString();
}
