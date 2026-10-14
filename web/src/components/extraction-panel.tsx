"use client";

// What the system read from each agent note, with the exact words it relied on highlighted.
// The agent confirms it as is, or edits a value; edited values carry the agent's word (confidence 1)
// and flow back into the case (a confirmed hardship signal makes hardship CONFIRMED).
import { SectionTitle } from "./page-header";
import { CheckCircledIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Card, Flex, Select, Switch, Text, TextField, Tooltip } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { api, humanize, type NoteExtraction, type TextExtraction } from "@/lib/api";
import { spring } from "./motion";

type Field = keyof Omit<TextExtraction, "source_id" | "case_id" | "extractor" | "extracted_at" | "confirmed_by_agent_id">;

export const FIELDS: { key: Field; label: string; kind: "signal" | "reason" | "bool" | "amount" | "date"; color: string }[] = [
  { key: "hardship_signal", label: "Hardship", kind: "signal", color: "amber" },
  { key: "stated_reason", label: "Stated reason", kind: "reason", color: "amber" },
  { key: "promise_intent", label: "Intends to pay", kind: "bool", color: "grass" },
  { key: "promised_amount", label: "Promised amount", kind: "amount", color: "grass" },
  { key: "promised_date", label: "Promised date", kind: "date", color: "grass" },
  { key: "dispute", label: "Disputes the debt", kind: "bool", color: "plum" },
  { key: "cease_request", label: "Asked us to stop", kind: "bool", color: "red" },
  { key: "third_party_present", label: "Third party present", kind: "bool", color: "blue" },
];
const SIGNALS = ["none", "possible", "clear"];
const REASONS = ["none", "job_loss", "reduced_income", "medical", "bereavement", "other"];

/** The note with every evidence span marked, coloured by the field it supports. */
export function Highlighted({ note, ex }: { note: string; ex: TextExtraction }) {
  const spans = FIELDS.flatMap((f) => {
    const e = ex[f.key].evidence;
    return e ? [{ start: e.char_start, end: e.char_end, f }] : [];
  })
    .sort((a, b) => a.start - b.start)
    .filter((s, i, all) => i === 0 || s.start >= all[i - 1].end); // overlapping quotes: keep the first
  const parts: React.ReactNode[] = [];
  let at = 0;
  spans.forEach((s, i) => {
    if (s.start > at) parts.push(note.slice(at, s.start));
    parts.push(
      <Tooltip key={i} content={s.f.label}>
        <mark style={{ background: `var(--${s.f.color}-a4)`, color: "inherit", borderRadius: 3, padding: "0 2px", boxShadow: `inset 0 -2px 0 var(--${s.f.color}-8)` }}>
          {note.slice(s.start, s.end)}
        </mark>
      </Tooltip>,
    );
    at = s.end;
  });
  parts.push(note.slice(at));
  return (
    <Text as="p" size="2" style={{ lineHeight: 1.7 }}>
      {parts}
    </Text>
  );
}

function NoteCard({ item, agentId, demo, onSaved }: { item: NoteExtraction; agentId: string; demo: boolean; onSaved: () => void }) {
  const ex = item.extraction;
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const value = (k: Field) => (k in edits ? edits[k] : ex[k].value);
  const set = (k: Field, v: unknown) => setEdits((e) => ({ ...e, [k]: v }));
  const changed = Object.keys(edits).length > 0;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.confirmExtraction(ex.source_id, agentId, edits, demo);
      setEdits({});
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card size="2" variant="surface">
      <Flex justify="between" align="center" mb="2" gap="2" wrap="wrap">
        <Text size="1" color="gray" className="tabular">
          {ex.source_id} · {ex.extractor} · {new Date(ex.extracted_at).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}
        </Text>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={ex.confirmed_by_agent_id ?? "unconfirmed"} initial={{ scale: 0.7, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={spring}>
            {ex.confirmed_by_agent_id ? (
              <Badge color="grass" variant="soft"><CheckCircledIcon /> confirmed by {ex.confirmed_by_agent_id}</Badge>
            ) : (
              <Badge color="gray" variant="outline">needs your confirmation</Badge>
            )}
          </motion.span>
        </AnimatePresence>
      </Flex>
      <Highlighted note={item.note} ex={ex} />
      <Box mt="3" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 10 }}>
        {FIELDS.map((f) => {
          const v = value(f.key);
          const conf = f.key in edits ? 1 : ex[f.key].confidence;
          return (
            <Box key={f.key} p="2" style={{ borderRadius: 8, background: f.key in edits ? "var(--accent-a3)" : "var(--gray-a2)" }}>
              <Flex justify="between" align="center" mb="1">
                <Text size="1" weight="medium" style={{ color: `var(--${f.color}-11)` }}>{f.label}</Text>
                <Tooltip content={f.key in edits ? "your edit" : "model confidence"}>
                  <Text size="1" color="gray" className="tabular">{Math.round(conf * 100)}%</Text>
                </Tooltip>
              </Flex>
              {f.kind === "bool" && (
                <Switch size="1" checked={Boolean(v)} onCheckedChange={(c) => set(f.key, c)} color={f.key === "cease_request" ? "red" : undefined} aria-label={f.label} />
              )}
              {(f.kind === "signal" || f.kind === "reason") && (
                <Select.Root size="1" value={String(v)} onValueChange={(x) => set(f.key, x)}>
                  <Select.Trigger aria-label={f.label} style={{ width: "100%" }} />
                  <Select.Content>
                    {(f.kind === "signal" ? SIGNALS : REASONS).map((o) => (
                      <Select.Item key={o} value={o}>{humanize(o)}</Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              )}
              {f.kind === "amount" && (
                <TextField.Root size="1" inputMode="decimal" placeholder="none" value={v == null ? "" : String(v)}
                  onChange={(e) => set(f.key, e.target.value === "" ? null : e.target.value)} aria-label={f.label} />
              )}
              {f.kind === "date" && (
                <TextField.Root size="1" type="date" value={v == null ? "" : String(v)}
                  onChange={(e) => set(f.key, e.target.value === "" ? null : e.target.value)} aria-label={f.label} />
              )}
            </Box>
          );
        })}
      </Box>
      {error && <Text as="p" size="1" color="red" mt="2">{error}</Text>}
      <Flex justify="end" gap="2" mt="3">
        {changed && <Button variant="soft" color="gray" onClick={() => setEdits({})}>Undo edits</Button>}
        <Button loading={busy} disabled={!changed && !!ex.confirmed_by_agent_id} onClick={() => void save()}>
          {changed ? "Save edits" : ex.confirmed_by_agent_id ? "Confirmed" : "Confirm as read"}
        </Button>
      </Flex>
    </Card>
  );
}

export function ExtractionPanel({ items, agentId, demo, onSaved }: { items: NoteExtraction[]; agentId: string; demo: boolean; onSaved: () => void }) {
  if (!items.length) return null;
  return (
    <Card size="3">
      <SectionTitle eyebrow="Text · local model, quoted" title="From the notes" mb="1" />
      <Text as="p" size="2" color="gray" mt="1" mb="4">
        What was read from each note, with the words it rests on highlighted. Confirm it, or correct it: a confirmed hardship
        signal makes hardship confirmed, and a stop request becomes a hard stop.
      </Text>
      <Flex direction="column" gap="3">
        <AnimatePresence initial={false}>
          {items.map((it) => (
            <motion.div key={it.extraction.source_id} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={spring}>
              <NoteCard item={it} agentId={agentId} demo={demo} onSaved={onSaved} />
            </motion.div>
          ))}
        </AnimatePresence>
      </Flex>
    </Card>
  );
}
