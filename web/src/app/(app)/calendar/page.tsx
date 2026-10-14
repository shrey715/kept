"use client";

import { PageHeader, SectionTitle } from "@/components/page-header";
import {
  CalendarIcon,
  CardStackIcon,
  CheckCircledIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DownloadIcon,
  ExternalLinkIcon,
  HeartIcon,
  Link2Icon,
  PaperPlaneIcon,
  TimerIcon,
} from "@radix-ui/react-icons";
import { Box, Callout, Flex, Popover, Skeleton, Text } from "@radix-ui/themes";
import { motion } from "motion/react";
import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { TierBadge } from "@/components/bits";
import { Rise, Stagger } from "@/components/motion";
import { download } from "@/lib/csv";
import { api, type CalendarEvent, type CalendarFeed, type Tier } from "@/lib/api";
import { googleLink, toIcs } from "@/lib/ics";
import { useSession } from "@/lib/session";

type Kind = CalendarEvent["kind"];
type Tint = "rose" | "butter" | "mint" | "ice" | "lilac";
type View = "month" | "week" | "agenda";

/** Each kind of event, its label and icon, and the tint it wears (promises by how they ended). */
const KINDS: { kind: Kind; label: string; icon: React.ReactNode; tint: Tint }[] = [
  { kind: "promise_due", label: "Promises due", icon: <CheckCircledIcon />, tint: "ice" },
  { kind: "contact", label: "Send windows", icon: <PaperPlaneIcon />, tint: "lilac" },
  { kind: "approval_deadline", label: "Approval deadlines", icon: <TimerIcon />, tint: "butter" },
  { kind: "payday", label: "Paydays", icon: <CardStackIcon />, tint: "mint" },
  { kind: "hardship_review", label: "Hardship reviews", icon: <HeartIcon />, tint: "rose" },
];
const LOOK = Object.fromEntries(KINDS.map((k) => [k.kind, k])) as Record<Kind, (typeof KINDS)[number]>;
const TIERS: [Tier | "none", string][] = [
  ["red", "Red"],
  ["amber", "Amber"],
  ["green", "Green"],
  ["none", "No tier"],
];

/** A promise wears how it ended: kept mint, broken rose, part-paid butter; open ones ice. */
function tintOf(e: CalendarEvent): Tint {
  if (e.kind === "promise_due") return e.status === "kept" ? "mint" : e.status === "broken" ? "rose" : e.status === "partially_kept" ? "butter" : "ice";
  return LOOK[e.kind].tint;
}

// ---------------------------------------------------------------- dates (local days; all-day events keep their UTC date)
const DAY = 86_400_000;
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const monday = (d: Date) => addDays(d, -((d.getDay() + 6) % 7));
const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const dayOf = (e: CalendarEvent) => (e.all_day ? e.start.slice(0, 10) : key(new Date(e.start)));
const timeOf = (e: CalendarEvent) =>
  e.all_day ? "All day" : new Date(e.start).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" });

function rangeFor(view: View, anchor: Date): { start: Date; end: Date } {
  if (view === "week") return { start: monday(anchor), end: addDays(monday(anchor), 6) };
  if (view === "agenda") return { start: anchor, end: addDays(anchor, 29) };
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  return { start: monday(first), end: addDays(monday(first), 41) }; // six weeks, Monday first
}

function shift(view: View, anchor: Date, dir: number): Date {
  if (view === "month") return new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1);
  return addDays(anchor, dir * (view === "week" ? 7 : 30));
}

const SCOPE: Record<CalendarFeed["scope"], string> = {
  own: "Your own cases: promises falling due, the send windows proposed for them, approval deadlines, paydays and hardship reviews.",
  queue: "The 500 cases in your queue, best first: promises, send windows, approval deadlines, paydays and hardship reviews.",
  aggregate: "Counts per day across the book; your role sees aggregates only, and days with fewer than 10 of a kind are left out.",
};

export default function CalendarPage() {
  const { me } = useSession();
  // a month grid is too tight on a phone: start there on the agenda (the page renders once a persona is known,
  // which is client-side only, so this can read the window)
  const [view, setView] = useState<View>(() =>
    typeof window !== "undefined" && window.matchMedia("(max-width: 640px)").matches ? "agenda" : "month",
  );
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [selected, setSelected] = useState(() => startOfDay(new Date()));
  const [kinds, setKinds] = useState<Set<Kind>>(() => new Set(KINDS.map((k) => k.kind)));
  const [tiers, setTiers] = useState<Set<string>>(() => new Set(TIERS.map((t) => t[0])));
  const { start, end } = useMemo(() => rangeFor(view, anchor), [view, anchor]);
  // what came back, and for which range: a stale range's events never show under a new heading
  const [got, setGot] = useState<{ range: string; feed?: CalendarFeed; error?: string } | null>(null);
  const range = `${key(start)}/${key(end)}`;
  const feed = got?.range === range ? (got.feed ?? null) : null;
  const error = got?.range === range ? (got.error ?? null) : null;

  useEffect(() => {
    if (!me) return;
    let live = true;
    const [a, b] = range.split("/");
    api.calendar(me, a, b).then(
      (f) => live && setGot({ range, feed: f }),
      (e: Error) => live && setGot({ range, error: e.message }),
    );
    return () => {
      live = false;
    };
  }, [me, range]);

  const shown = useMemo(
    () => (feed?.events ?? []).filter((e) => kinds.has(e.kind) && tiers.has(e.tier ?? "none")),
    [feed, kinds, tiers],
  );
  const byDay = useMemo(() => {
    const m = new Map<string, CalendarEvent[]>();
    for (const e of shown) m.set(dayOf(e), [...(m.get(dayOf(e)) ?? []), e]);
    return m;
  }, [shown]);
  const today = key(new Date());
  const peak = useMemo(() => Math.max(0, ...[...byDay.values()].map((v) => v.length)), [byDay]);
  const perKind = useMemo(() => {
    const m = new Map<Kind, number>();
    for (const e of shown) m.set(e.kind, (m.get(e.kind) ?? 0) + (e.count ?? 1));
    return m;
  }, [shown]);
  const fitRef = useRef<HTMLDivElement>(null);
  const fit = useFitHeight(fitRef, [view, feed == null, error]);
  const toggle = <T,>(set: Set<T>, v: T) => {
    const n = new Set(set);
    if (n.has(v)) n.delete(v);
    else n.add(v);
    return n;
  };
  const label =
    view === "month"
      ? anchor.toLocaleDateString("en-CA", { month: "long", year: "numeric" })
      : `${start.toLocaleDateString("en-CA", { month: "short", day: "numeric" })} – ${end.toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" })}`;
  const exportAll = () =>
    download(`kept-${view}-${key(start)}.ics`, toIcs(shown, window.location.origin, tintOf, "Kept · coming up"), "text/calendar");
  if (!me) return null;

  return (
    <Stagger>
      <Rise>
        <PageHeader
          icon={<CalendarIcon />}
          eyebrow="Calendar"
          title="Everything coming up, on one calendar."
          sub={feed ? SCOPE[feed.scope] : "Promises due, send windows, approval deadlines, paydays and hardship reviews."}
          actions={
            <button className="k-strong-btn" onClick={exportAll} disabled={!shown.length} title="Download the events on screen as an .ics file">
              <DownloadIcon /> Export .ics
            </button>
          }
        />
      </Rise>

      <Rise>
        <Flex gap="3" align="center" wrap="wrap" justify="between">
          <Flex gap="2" align="center" wrap="wrap">
            <div className="k-tabs" role="tablist" aria-label="View">
              {(["month", "week", "agenda"] as View[]).map((v) => (
                <button key={v} role="tab" aria-selected={view === v} className="k-tab" data-active={view === v} onClick={() => setView(v)}>
                  {v[0].toUpperCase() + v.slice(1)}
                </button>
              ))}
            </div>
            <button className="k-round-btn" aria-label="Previous" onClick={() => setAnchor((a) => shift(view, a, -1))}>
              <ChevronLeftIcon />
            </button>
            <button className="k-tab" onClick={() => setAnchor(startOfDay(new Date()))}>
              Today
            </button>
            <button className="k-round-btn" aria-label="Next" onClick={() => setAnchor((a) => shift(view, a, 1))}>
              <ChevronRightIcon />
            </button>
            <h2 className="k-tpanel-title" style={{ marginLeft: 6 }}>
              {label}
            </h2>
          </Flex>
          <Text size="1" color="gray" className="tabular">
            {feed ? `${shown.length.toLocaleString("en-CA")} of ${feed.events.length.toLocaleString("en-CA")} events${feed.truncated ? " (first 3,000)" : ""}` : ""}
          </Text>
        </Flex>
      </Rise>

      <Rise>
        <Flex gap="2" mt="3" wrap="wrap" align="center">
          {KINDS.map((k) => (
            <button key={k.kind} className={`k-filter t-${k.tint}`} data-on={kinds.has(k.kind)} onClick={() => setKinds((s) => toggle(s, k.kind))} aria-pressed={kinds.has(k.kind)}>
              <span className="k-filter-dot" />
              {k.label}
              {feed && <span className="k-filter-n tabular">{(perKind.get(k.kind) ?? 0).toLocaleString("en-CA")}</span>}
            </button>
          ))}
          {feed?.scope !== "aggregate" && (
            <>
              <span className="k-filter-sep" aria-hidden />
              {TIERS.map(([t, l]) => (
                <button key={t} className="k-filter" data-on={tiers.has(t)} onClick={() => setTiers((s) => toggle(s, t))} aria-pressed={tiers.has(t)}>
                  {l}
                </button>
              ))}
            </>
          )}
        </Flex>
      </Rise>

      {error && (
        <Callout.Root color="red" mt="4">
          <Callout.Text>Couldn&apos;t load the calendar: {error}</Callout.Text>
        </Callout.Root>
      )}
      <Rise>
        <div className="k-cal-wrap" data-panel={view === "month"} ref={fitRef} style={fit && view !== "agenda" ? { height: fit } : undefined}>
          <div className="k-cal-pane">
            {!feed && !error ? (
              <Skeleton height={`${fit ?? 560}px`} />
            ) : view === "month" ? (
              <MonthGrid start={start} month={anchor.getMonth()} byDay={byDay} today={today} selected={key(selected)} onSelect={setSelected} peak={peak} height={fit} />
            ) : view === "week" ? (
              <WeekView start={start} byDay={byDay} today={today} onMore={(d) => setSelected(startOfDay(d))} height={fit} />
            ) : (
              <Agenda start={start} end={end} byDay={byDay} today={today} />
            )}
          </div>
          {view === "month" && feed && (
            <DayPanel
              day={selected}
              evs={byDay.get(key(selected)) ?? []}
              today={today}
              height={fit}
              onAgenda={() => (setAnchor(startOfDay(selected)), setView("agenda"))}
              feedPath={api.calendarFeedPath(me)}
            />
          )}
        </div>
      </Rise>
    </Stagger>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** The height left on screen below `ref` on a desktop, so the month and week views fit the window instead of making
 * the page scroll; null on narrow screens, where the views flow naturally. */
function useFitHeight(ref: React.RefObject<HTMLElement | null>, deps: unknown[]): number | null {
  const [h, setH] = useState<number | null>(null);
  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current;
      if (!el || window.innerWidth <= 900) return setH(null);
      setH(Math.max(460, Math.floor(window.innerHeight - el.getBoundingClientRect().top - 52)));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return h;
}

/** How many event chips fit in `space` pixels, leaving room for a "+N more" line; at least one. */
const fitting = (space: number, chip: number) => Math.max(1, Math.floor((space - 20) / chip));

function MonthGrid({ start, month, byDay, today, selected, onSelect, peak, height }: { start: Date; month: number; byDay: Map<string, CalendarEvent[]>; today: string; selected: string; onSelect: (d: Date) => void; peak: number; height: number | null }) {
  // each day shows its first event when there's room; the rest is the count and a dot per kind
  const roomy = height == null || (height - 77) / 6 > 104;
  return (
    <div className="k-cal k-dots" data-fit={height != null}>
      <div className="k-cal-grid k-cal-head" aria-hidden>
        {WEEKDAYS.map((w) => (
          <span key={w}>{w}</span>
        ))}
      </div>
      <div className="k-cal-grid" role="grid">
        {Array.from({ length: 42 }, (_, i) => {
          const d = addDays(start, i);
          const k = key(d);
          const evs = byDay.get(k) ?? [];
          const load = peak ? Math.sqrt(evs.length / peak) : 0; // sqrt: a quiet day still shows
          return (
            <div
              key={i}
              role="gridcell"
              tabIndex={0}
              aria-selected={k === selected}
              aria-label={`${d.toDateString()}: ${evs.length} event${evs.length === 1 ? "" : "s"}`}
              className="k-cal-cell"
              data-out={d.getMonth() !== month}
              data-today={k === today}
              data-selected={k === selected}
              style={{ "--load": load.toFixed(3) } as React.CSSProperties}
              onClick={() => onSelect(d)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(d))}
            >
              <div className="k-cal-cell-head">
                <span className="k-cal-num">{d.getDate()}</span>
                {evs.length > 0 && <span className="k-cal-count tabular">{evs.length}</span>}
              </div>
              {roomy && evs[0] && (
                <div className="k-cal-evs" onClick={(e) => e.stopPropagation()}>
                  <EventChip e={evs[0]} compact />
                </div>
              )}
              {evs.length > 0 && <KindDots evs={evs} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** A dot per kind of event on a day, with how many: the day's mix at a glance. */
function KindDots({ evs }: { evs: CalendarEvent[] }) {
  const n = new Map<Kind, number>();
  for (const e of evs) n.set(e.kind, (n.get(e.kind) ?? 0) + (e.count ?? 1));
  return (
    <div className="k-cal-kinds" aria-hidden>
      {KINDS.filter((k) => n.has(k.kind)).map((k) => (
        <span key={k.kind} className={`k-cal-kind t-${k.tint}`} title={`${k.label}: ${n.get(k.kind)}`}>
          <i />
          {n.get(k.kind)}
        </span>
      ))}
    </div>
  );
}

/** The selected day beside the grid: its date, the mix by kind, and as many events as fit; then the feed. */
function DayPanel({ day, evs, today, height, onAgenda, feedPath }: { day: Date; evs: CalendarEvent[]; today: string; height: number | null; onAgenda: () => void; feedPath: string }) {
  const sorted = [...evs].sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start));
  // as many rows as the list's measured height holds (a row is 50px)
  const listRef = useRef<HTMLDivElement>(null);
  const [space, setSpace] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el || height == null) return setSpace(null);
    const ro = new ResizeObserver(() => setSpace(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);
  const rows = space == null ? 8 : Math.max(1, Math.floor(space / 50)); // the "+N more" button sits below the list
  const n = new Map<Kind, number>();
  for (const e of evs) n.set(e.kind, (n.get(e.kind) ?? 0) + 1);
  return (
    <aside className="k-day-panel" aria-label="The selected day">
      <div className="k-day-card">
        <Flex align="end" justify="between" gap="3">
          <div>
            <div className="k-eyebrow">{key(day) === today ? "Today" : day.toLocaleDateString("en-CA", { weekday: "long" })}</div>
            <div className="k-day-date">{day.toLocaleDateString("en-CA", { month: "long", day: "numeric" })}</div>
          </div>
          <span className="k-badge tabular">{evs.length} event{evs.length === 1 ? "" : "s"}</span>
        </Flex>
        {evs.length > 0 && (
          <div className="k-day-mix" aria-hidden>
            {KINDS.filter((k) => n.has(k.kind)).map((k) => (
              <span key={k.kind} className={`t-${k.tint}`} style={{ flex: n.get(k.kind) }} title={`${k.label}: ${n.get(k.kind)}`} />
            ))}
          </div>
        )}
        <div className="k-day-list" ref={listRef}>
          {sorted.length ? (
            sorted.slice(0, rows).map((e) => <DayRow key={e.id} e={e} />)
          ) : (
            <Text as="p" size="2" color="gray" style={{ padding: "18px 2px" }}>
              Nothing due this day.
            </Text>
          )}
        </div>
        {sorted.length > rows && (
          <button className="k-tab" onClick={onAgenda} style={{ alignSelf: "flex-start" }}>
            +{sorted.length - rows} more in the agenda <ChevronRightIcon />
          </button>
        )}
      </div>
      <SubscribeCard feedPath={feedPath} />
    </aside>
  );
}

function DayRow({ e }: { e: CalendarEvent }) {
  const look = LOOK[e.kind];
  return (
    <Popover.Root>
      <Popover.Trigger>
        <button className="k-day-row">
          <span className={`k-ava t-${tintOf(e)}`} aria-hidden style={{ width: 32, height: 32 }}>
            {look.icon}
          </span>
          <span className="k-day-row-txt">
            <b>{e.count != null ? e.title : e.display_name ?? e.title}</b>
            <span>{[timeOf(e), e.count != null ? null : e.title, e.tier].filter(Boolean).join(" · ")}</span>
          </span>
        </button>
      </Popover.Trigger>
      <EventDetail e={e} />
    </Popover.Root>
  );
}

/** Keep these in a calendar app: a live subscription (refreshed hourly), its link, or a one-off file. */
function SubscribeCard({ feedPath }: { feedPath: string }) {
  const [copied, setCopied] = useState(false);
  const url = typeof window !== "undefined" ? `${window.location.origin}${feedPath}` : feedPath;
  const webcal = url.replace(/^https?:/, "webcal:");
  return (
    <div className="k-sub-card">
      <div className="k-sub-title">Keep it in your calendar</div>
      <p>Subscribe once: Google, Outlook or Apple Calendar refresh this feed every hour.</p>
      <Flex gap="2" wrap="wrap">
        <a className="k-sub-btn" href={webcal}>
          <CalendarIcon /> Subscribe
        </a>
        <button
          className="k-sub-btn ghost"
          onClick={() => {
            void navigator.clipboard?.writeText(url).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1600);
            });
          }}
        >
          {copied ? <CheckCircledIcon /> : <Link2Icon />} {copied ? "Copied" : "Copy link"}
        </button>
      </Flex>
    </div>
  );
}

function WeekView({ start, byDay, today, onMore, height }: { start: Date; byDay: Map<string, CalendarEvent[]>; today: string; onMore: (d: Date) => void; height: number | null }) {
  const maxIn = height ? fitting(height - 24 - 44, 34) : Infinity; // a day's column minus its padding and header
  return (
    <div className="k-week" data-fit={height != null}>
      {Array.from({ length: 7 }, (_, i) => {
        const d = addDays(start, i);
        const evs = [...(byDay.get(key(d)) ?? [])].sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start));
        return (
          <section key={i} className="k-week-day" data-today={key(d) === today}>
            <header>
              <span className="k-eyebrow" style={{ color: "var(--gray-11)" }}>
                {WEEKDAYS[i]}
              </span>
              <span className="k-week-num">{d.getDate()}</span>
            </header>
            <div className="k-cal-evs">
              {evs.length ? evs.slice(0, maxIn).map((e) => <EventChip key={e.id} e={e} />) : <Text size="1" color="gray">Nothing due</Text>}
              {evs.length > maxIn && (
                <button className="k-cal-more" onClick={() => onMore(d)}>
                  +{evs.length - maxIn} more
                </button>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function Agenda({ start, end, byDay, today }: { start: Date; end: Date; byDay: Map<string, CalendarEvent[]>; today: string }) {
  const days = Array.from({ length: Math.round((end.getTime() - start.getTime()) / DAY) + 1 }, (_, i) => addDays(start, i)).filter((d) => byDay.has(key(d)));
  if (!days.length)
    return (
      <div className="k-card" style={{ padding: 32, textAlign: "center" }}>
        <Text color="gray">Nothing coming up in these 30 days for the filters you&apos;ve picked.</Text>
      </div>
    );
  const tomorrow = key(addDays(new Date(), 1));
  return (
    <Flex direction="column" gap="3">
      {days.map((d) => (
        <section key={key(d)} className="k-card" style={{ padding: "18px 18px 10px" }}>
          <SectionTitle
            eyebrow={key(d) === today ? "Today" : key(d) === tomorrow ? "Tomorrow" : d.toLocaleDateString("en-CA", { weekday: "long" })}
            title={d.toLocaleDateString("en-CA", { month: "long", day: "numeric" })}
            aside={<span className="k-badge">{byDay.get(key(d))!.length}</span>}
            mb="2"
          />
          {[...byDay.get(key(d))!]
            .sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start))
            .map((e) => (
              <AgendaRow key={e.id} e={e} />
            ))}
        </section>
      ))}
    </Flex>
  );
}

function AgendaRow({ e }: { e: CalendarEvent }) {
  const look = LOOK[e.kind];
  return (
    <div className="k-agenda-row">
      <Text size="1" color="gray" className="tabular" style={{ width: 64, flex: "none" }}>
        {timeOf(e)}
      </Text>
      <span className={`k-ava t-${tintOf(e)}`} aria-hidden>
        {look.icon}
      </span>
      <Box className="k-agenda-main" style={{ minWidth: 0, flex: 1 }}>
        <Text as="div" size="2" weight="medium">
          {e.title}
        </Text>
        <Text as="div" size="1" color="gray" truncate>
          {[e.display_name, e.case_id, e.detail].filter(Boolean).join(" · ")}
        </Text>
      </Box>
      {e.tier && <TierBadge tier={e.tier} long={false} size="1" />}
      <EventActions e={e} />
    </div>
  );
}

/** Add one event to a calendar (.ics or Google), and open its case. */
function EventActions({ e, wide = false }: { e: CalendarEvent; wide?: boolean }) {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return (
    <Flex gap="2" align="center" wrap="wrap">
      <button
        className={wide ? "k-tab" : "k-round-btn k-round-sm"}
        onClick={() => download(`kept-${e.id}.ics`, toIcs([e], origin, tintOf, e.title), "text/calendar")}
        aria-label="Add to calendar (.ics)"
        title="Add to calendar (.ics)"
      >
        <DownloadIcon />
        {wide && " Add to calendar"}
      </button>
      <a className={wide ? "k-tab" : "k-round-btn k-round-sm"} href={googleLink(e, origin)} target="_blank" rel="noreferrer" aria-label="Add to Google Calendar" title="Add to Google Calendar" style={{ textDecoration: "none" }}>
        <ExternalLinkIcon />
        {wide && " Google Calendar"}
      </a>
      {e.case_id && (
        <Link href={`/cases/${encodeURIComponent(e.case_id)}`} className={wide ? "k-strong-btn" : "k-round-btn k-round-sm"} aria-label="Open the case" title="Open the case" style={{ textDecoration: "none" }}>
          {wide ? "Open the case" : <ChevronRightIcon />}
        </Link>
      )}
    </Flex>
  );
}

/** One event on the grid: a tinted pill; clicking it shows the details, the case and the calendar links. */
function EventChip({ e, compact = false }: { e: CalendarEvent; compact?: boolean }) {
  return (
    <Popover.Root>
      <Popover.Trigger>
        <motion.button className={`k-ev t-${tintOf(e)}`} data-compact={compact} whileTap={{ scale: 0.97 }} aria-label={`${e.title}${e.display_name ? `, ${e.display_name}` : ""}`}>
          <span className="k-ev-dot" aria-hidden />
          <span className="txt">
            {!e.all_day && <b>{timeOf(e)} </b>}
            {e.count != null ? e.title : e.display_name ?? e.title}
          </span>
        </motion.button>
      </Popover.Trigger>
      <EventDetail e={e} />
    </Popover.Root>
  );
}

/** An event's details, its case and the calendar links (the popover on a chip or a day row). */
function EventDetail({ e }: { e: CalendarEvent }) {
  const look = LOOK[e.kind];
  return (
    <Popover.Content className="k-pop" width="340px">
      <Flex gap="3" align="start">
        <span className={`k-ava t-${tintOf(e)}`} aria-hidden style={{ width: 36, height: 36 }}>
          {look.icon}
        </span>
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Text as="div" size="1" color="gray">
            {look.label.replace(/s$/, "")} · {e.all_day ? new Date(e.start).toLocaleDateString("en-CA", { timeZone: "UTC", dateStyle: "medium" }) : `${new Date(e.start).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}${e.end ? ` – ${new Date(e.end).toLocaleTimeString("en-CA", { timeStyle: "short" })}` : ""}`}
          </Text>
          <Text as="div" size="3" weight="medium" mt="1">
            {e.title}
          </Text>
          {(e.display_name || e.case_id) && (
            <Text as="div" size="2" mt="1">
              {[e.display_name, e.case_id].filter(Boolean).join(" · ")}
            </Text>
          )}
          {e.detail && (
            <Text as="p" size="2" color="gray" mt="1">
              {e.detail}
            </Text>
          )}
          <Flex gap="2" mt="2" align="center" wrap="wrap">
            {e.tier && <TierBadge tier={e.tier} long={false} size="1" />}
            {e.status && <span className="k-badge">{e.status.replaceAll("_", " ")}</span>}
          </Flex>
        </Box>
      </Flex>
      <Box mt="3">
        <EventActions e={e} wide />
      </Box>
    </Popover.Content>
  );
}
