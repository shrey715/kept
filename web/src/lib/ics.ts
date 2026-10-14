// Calendar files by hand (RFC 5545): CRLF lines folded at 75 octets, text escaped, all-day events as DATE
// values (DTEND the day after), timed events in UTC. Plus a Google Calendar "add event" link.
import type { CalendarEvent } from "./api";

/** The CSS colour name each tint exports as (RFC 7986 COLOR): a hint calendars may use. */
const COLOUR: Record<string, string> = { rose: "pink", butter: "khaki", mint: "mediumseagreen", ice: "lightblue", lilac: "plum" };

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`;
const stamp = (d: Date) => `${ymd(d)}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
const nextDay = (d: Date) => new Date(d.getTime() + 86_400_000);
const escape = (t: string) => t.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

/** Fold a content line at 75 octets (UTF-8), continuation lines starting with one space. */
function fold(line: string): string {
  const enc = new TextEncoder();
  const out: string[] = [];
  let cur = "";
  for (const ch of line) {
    if (enc.encode(cur + ch).length > (out.length ? 74 : 75)) {
      out.push(cur);
      cur = ch;
    } else cur += ch;
  }
  out.push(cur);
  return out.join("\r\n ");
}

/** When an event starts and ends: all-day events cover their date, timed ones their window (30 min if none). */
function span(e: CalendarEvent): { start: Date; end: Date } {
  const start = new Date(e.start);
  if (e.all_day) return { start, end: nextDay(start) };
  return { start, end: e.end ? new Date(e.end) : new Date(start.getTime() + 30 * 60_000) };
}

export function caseUrl(e: CalendarEvent, origin: string): string | null {
  return e.case_id ? `${origin}/cases/${encodeURIComponent(e.case_id)}` : null;
}

function describe(e: CalendarEvent, origin: string): string {
  const who = [e.display_name, e.case_id].filter(Boolean).join(" · ");
  const link = caseUrl(e, origin);
  return [who, e.detail, e.status ? `Status: ${e.status.replaceAll("_", " ")}` : null, link ? `Open the case: ${link}` : null]
    .filter(Boolean)
    .join("\n");
}

export function toIcs(events: CalendarEvent[], origin: string, tintOf: (e: CalendarEvent) => string, name = "Kept"): string {
  const now = stamp(new Date());
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Sharpe Shooters//Kept//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", `X-WR-CALNAME:${escape(name)}`];
  for (const e of events) {
    const { start, end } = span(e);
    const link = caseUrl(e, origin);
    lines.push(
      "BEGIN:VEVENT",
      `UID:${e.id}@kept.sharpe-shooters`,
      `DTSTAMP:${now}`,
      ...(e.all_day ? [`DTSTART;VALUE=DATE:${ymd(start)}`, `DTEND;VALUE=DATE:${ymd(end)}`] : [`DTSTART:${stamp(start)}`, `DTEND:${stamp(end)}`]),
      `SUMMARY:${escape(e.display_name ? `${e.title} · ${e.display_name}` : e.title)}`,
      `DESCRIPTION:${escape(describe(e, origin))}`,
      `CATEGORIES:${[e.kind, e.tier].filter(Boolean).map((c) => escape(String(c))).join(",")}`,
      `COLOR:${COLOUR[tintOf(e)] ?? "lightblue"}`,
      ...(link ? [`URL:${link}`] : []),
      "TRANSP:TRANSPARENT",
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

/** Google Calendar's "add event" page, prefilled (all-day dates are end-exclusive, like DTEND). */
export function googleLink(e: CalendarEvent, origin: string): string {
  const { start, end } = span(e);
  const dates = e.all_day ? `${ymd(start)}/${ymd(end)}` : `${stamp(start)}/${stamp(end)}`;
  const p = new URLSearchParams({
    action: "TEMPLATE",
    text: e.display_name ? `${e.title} · ${e.display_name}` : e.title,
    dates,
    details: describe(e, origin),
  });
  return `https://calendar.google.com/calendar/render?${p.toString()}`;
}
