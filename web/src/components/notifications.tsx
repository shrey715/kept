"use client";

import { BellIcon, CheckCircledIcon, Cross2Icon, ExclamationTriangleIcon, InfoCircledIcon, LightningBoltIcon } from "@radix-ui/react-icons";
import { Popover, Text } from "@radix-ui/themes";
import { AnimatePresence, motion, useAnimationControls } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Notification } from "@/lib/api";
import type { Persona } from "@/lib/session";

type Severity = Notification["severity"];
const RANK: Record<Severity, number> = { critical: 0, action: 1, success: 2, info: 3 };
const LOOK: Record<Severity, { icon: React.ReactNode; color: string }> = {
  critical: { icon: <ExclamationTriangleIcon />, color: "var(--red-9)" },
  action: { icon: <LightningBoltIcon />, color: "var(--k-red)" },
  success: { icon: <CheckCircledIcon />, color: "var(--grass-9)" },
  info: { icon: <InfoCircledIcon />, color: "var(--gray-9)" },
};
const POLL_MS = 20_000;
const MAX_POLL_MS = 300_000;
const MAX_TOASTS = 3;
const BURST = 3; // more new ones than this in one poll become a single summary toast

type Toast = { key: string; n: Notification; count?: number };

/**
 * The feed for one person: polls while the tab is visible (refetches on focus), backs off on errors, and hands
 * each notification it hasn't seen before to `onNew` once (the first load only fills the bell, no toasts).
 */
function useFeed(me: Persona, onNew: (ns: Notification[]) => void) {
  const [items, setItems] = useState<Notification[]>([]);
  const [readUpto, setReadUpto] = useState<string | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const onNewRef = useRef(onNew);
  useEffect(() => {
    onNewRef.current = onNew;
  }, [onNew]);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = POLL_MS;
    seen.current = null;
    const tick = async () => {
      if (document.visibilityState !== "visible") return; // resumes on visibilitychange
      try {
        const feed = await api.notifications(me);
        if (!live) return;
        setItems(feed.items);
        setReadUpto((r) => (r && feed.read_upto && ms(r) > ms(feed.read_upto) ? r : (feed.read_upto ?? r)));
        const fresh = seen.current ? feed.items.filter((n) => !seen.current!.has(n.id)) : [];
        seen.current = new Set(feed.items.map((n) => n.id));
        if (fresh.length) onNewRef.current(fresh);
        delay = POLL_MS;
      } catch {
        delay = Math.min(delay * 2, MAX_POLL_MS); // the API is down or restarting: back off
      }
      if (live) timer = setTimeout(tick, delay);
    };
    const wake = () => {
      if (document.visibilityState !== "visible") return;
      clearTimeout(timer);
      void tick();
    };
    void tick();
    document.addEventListener("visibilitychange", wake);
    return () => {
      live = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [me]);

  return { items, readUpto, setReadUpto };
}

/** The toast queue: highest severity first, no duplicates, bursts coalesced, at most three on screen. */
function useToasts() {
  const [shown, setShown] = useState<Toast[]>([]);
  const waiting = useRef<Toast[]>([]);
  const ids = useRef(new Set<string>());

  const pump = useCallback(() => {
    setShown((s) => {
      const room = MAX_TOASTS - s.length;
      if (room <= 0 || !waiting.current.length) return s;
      const next = waiting.current.splice(0, room);
      return [...s, ...next];
    });
  }, []);

  const push = useCallback(
    (ns: Notification[]) => {
      const fresh = ns.filter((n) => !ids.current.has(n.id));
      fresh.forEach((n) => ids.current.add(n.id));
      if (!fresh.length) return;
      const sorted = [...fresh].sort((a, b) => RANK[a.severity] - RANK[b.severity]);
      const batch: Toast[] =
        sorted.length > BURST
          ? [{ key: `burst-${sorted[0].id}`, n: sorted[0], count: sorted.length }] // one summary, led by the most urgent
          : sorted.map((n) => ({ key: n.id, n }));
      waiting.current = [...waiting.current, ...batch].sort((a, b) => RANK[a.n.severity] - RANK[b.n.severity]);
      pump();
    },
    [pump],
  );

  const dismiss = useCallback(
    (key: string) => {
      setShown((s) => s.filter((t) => t.key !== key));
      setTimeout(pump, 250); // let the exit animation start before the next one slides in
    },
    [pump],
  );

  return { shown, push, dismiss };
}

const ms = (iso: string) => Date.parse(iso); // offsets differ (API vs DuckDB): compare instants, not strings

function ago(at: string) {
  const s = Math.max(0, (Date.now() - new Date(at).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function NotificationCenter({ me }: { me: Persona }) {
  const router = useRouter();
  const bell = useAnimationControls();
  const { shown, push, dismiss } = useToasts();
  const onNew = useCallback(
    (ns: Notification[]) => {
      push(ns);
      void bell.start({ rotate: [0, -16, 14, -10, 8, -4, 0], transition: { duration: 0.7 } });
    },
    [push, bell],
  );
  const { items, readUpto, setReadUpto } = useFeed(me, onNew);
  const [tab, setTab] = useState<"all" | "unread">("all");
  const [open, setOpen] = useState(false);
  const unreadOf = (n: Notification) => !readUpto || ms(n.at) > ms(readUpto);
  const unread = items.filter(unreadOf).length;
  const list = tab === "unread" ? items.filter(unreadOf) : items;

  function markAll() {
    const upto = items[0]?.at ?? new Date().toISOString();
    setReadUpto(upto); // optimistic; the server keeps the furthest point any tab has read
    void api.markRead(me.userId, upto).catch(() => undefined);
  }

  function go(n: Notification) {
    setOpen(false);
    if (n.href) router.push(n.href);
  }

  return (
    <>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger>
          <button className="k-round-btn" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} style={{ position: "relative" }}>
            <motion.span animate={bell} style={{ display: "grid", transformOrigin: "50% 10%" }}>
              <BellIcon width={18} height={18} />
            </motion.span>
            <AnimatePresence>
              {unread > 0 && (
                <motion.span
                  key="badge"
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  exit={{ scale: 0 }}
                  transition={{ type: "spring", stiffness: 500, damping: 22 }}
                  className="k-bell-badge"
                >
                  <motion.span key={unread} initial={{ y: -8, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
                    {unread > 9 ? "9+" : unread}
                  </motion.span>
                </motion.span>
              )}
            </AnimatePresence>
          </button>
        </Popover.Trigger>
        <Popover.Content align="end" sideOffset={10} className="k-pop" style={{ width: "min(380px, calc(100vw - 24px))", padding: 0 }}>
          <motion.div initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 420, damping: 32 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 16px 10px" }}>
              <Text size="4" weight="medium" style={{ letterSpacing: "-0.02em" }}>
                Notifications
              </Text>
              {unread > 0 && <span className="k-badge">{unread} new</span>}
              <button onClick={markAll} disabled={!unread} className="k-text-btn" style={{ marginLeft: "auto" }}>
                Mark all read
              </button>
            </div>
            <div className="k-tabs" style={{ padding: "0 16px 12px" }} role="tablist">
              {(["all", "unread"] as const).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} className="k-tab" data-active={tab === t} onClick={() => setTab(t)} style={{ height: 32 }}>
                  {t === "all" ? "All" : "Unread"}
                </button>
              ))}
            </div>
            <div style={{ maxHeight: 420, overflowY: "auto", padding: "0 8px 8px" }}>
              {list.length === 0 && (
                <div style={{ padding: "36px 16px", textAlign: "center" }}>
                  <Text size="2" color="gray">
                    {tab === "unread" ? "You're all caught up." : "Nothing in the last seven days."}
                  </Text>
                </div>
              )}
              <AnimatePresence initial={false}>
                {list.map((n, i) => (
                  <motion.button
                    key={n.id}
                    layout
                    initial={{ opacity: 0, x: 10 }}
                    animate={{ opacity: 1, x: 0, transition: { delay: Math.min(i, 8) * 0.03 } }}
                    exit={{ opacity: 0, x: -10 }}
                    onClick={() => go(n)}
                    className="k-note"
                    data-unread={unreadOf(n)}
                  >
                    <span className="k-chip" style={{ width: 34, height: 34, borderRadius: 10, color: LOOK[n.severity].color }}>
                      {LOOK[n.severity].icon}
                    </span>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <Text as="div" size="2" weight="medium" truncate>
                        {n.title}
                      </Text>
                      {n.body && (
                        <Text as="div" size="1" color="gray" truncate>
                          {n.body}
                        </Text>
                      )}
                      <Text as="div" size="1" color="gray" mt="1">
                        {ago(n.at)}
                      </Text>
                    </span>
                    {unreadOf(n) && <span className="k-dot" aria-label="unread" />}
                  </motion.button>
                ))}
              </AnimatePresence>
            </div>
          </motion.div>
        </Popover.Content>
      </Popover.Root>

      <div className="k-toasts" aria-live="polite">
        <AnimatePresence>
          {shown.map((t) => (
            <ToastCard key={t.key} t={t} onClose={() => dismiss(t.key)} onOpen={() => (t.count ? setOpen(true) : go(t.n))} />
          ))}
        </AnimatePresence>
      </div>
    </>
  );
}

function ToastCard({ t, onClose, onOpen }: { t: Toast; onClose: () => void; onOpen: () => void }) {
  const [hover, setHover] = useState(false);
  useEffect(() => {
    if (hover || t.n.severity === "critical") return; // critical stays until dismissed; hovering pauses the timer
    const id = setTimeout(onClose, 6000);
    return () => clearTimeout(id);
  }, [hover, onClose, t.n.severity]);
  const look = LOOK[t.n.severity];
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 40, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.96, transition: { duration: 0.18 } }}
      transition={{ type: "spring", stiffness: 380, damping: 30 }}
      className="k-toast"
      role="status"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <span className="k-chip" style={{ width: 34, height: 34, borderRadius: 10, color: look.color }}>
        {look.icon}
      </span>
      <button onClick={onOpen} style={{ all: "unset", cursor: "pointer", minWidth: 0, flex: 1 }}>
        <Text as="div" size="2" weight="medium" truncate>
          {t.count ? `${t.count} new notifications` : t.n.title}
        </Text>
        <Text as="div" size="1" color="gray" truncate>
          {t.count ? `Most urgent: ${t.n.title}` : t.n.body}
        </Text>
      </button>
      <button onClick={onClose} aria-label="Dismiss" className="k-text-btn" style={{ padding: 4 }}>
        <Cross2Icon />
      </button>
    </motion.div>
  );
}
