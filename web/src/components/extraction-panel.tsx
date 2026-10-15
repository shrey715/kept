"use client";

// What the system read from each agent note, with the exact words it relied on highlighted.
// The agent confirms it as is, or edits a value; edited values carry the agent's word (confidence 1)
// and flow back into the case (a confirmed hardship signal makes hardship CONFIRMED).
import { SectionTitle } from "./page-header";
import { CheckCircledIcon, ChevronDownIcon, ChevronUpIcon, FileTextIcon } from "@radix-ui/react-icons";
import { Card, Flex, Select, Switch, Text, TextField, Tooltip } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { api, humanize, type NoteExtraction, type TextExtraction } from "@/lib/api";
import { spring } from "./motion";

type Field = keyof Omit<TextExtraction, "source_id" | "case_id" | "extractor" | "extracted_at" | "confirmed_by_agent_id">;

export const FIELDS: { key: Field; label: string; kind: "signal" | "reason" | "bool" | "amount" | "date"; color: string; tint: string }[] = [
  { key: "hardship_signal", label: "Hardship", kind: "signal", color: "amber", tint: "butter" },
  { key: "stated_reason", label: "Stated reason", kind: "reason", color: "amber", tint: "butter" },
  { key: "promise_intent", label: "Intends to pay", kind: "bool", color: "grass", tint: "mint" },
  { key: "promised_amount", label: "Promised amount", kind: "amount", color: "grass", tint: "mint" },
  { key: "promised_date", label: "Promised date", kind: "date", color: "grass", tint: "mint" },
  { key: "dispute", label: "Disputes the debt", kind: "bool", color: "plum", tint: "lilac" },
  { key: "cease_request", label: "Asked us to stop", kind: "bool", color: "red", tint: "rose" },
  { key: "third_party_present", label: "Third party present", kind: "bool", color: "blue", tint: "ice" },
];

/** Whether a field found something worth showing (a signal, a reason, a yes, an amount or a date). */
const found = (kind: string, v: unknown) => (kind === "bool" ? Boolean(v) : v != null && v !== "" && v !== "none");
const shown = (kind: string, v: unknown) =>
  kind === "bool"
    ? "Yes"
    : kind === "amount"
      ? `$${Number(v).toLocaleString("en-CA")}`
      : kind === "date"
        ? new Date(`${v}T00:00:00`).toLocaleDateString("en-CA", { month: "short", day: "numeric" })
        : humanize(String(v)).replace(/^./, (c) => c.toUpperCase());
/** Who read the note: the fast classifier that backfilled history, or the local language model. */
const reader = (x: string) => (x.startsWith("setfit") ? "Classifier" : x.startsWith("llm") ? "Qwen3.8 (local)" : x.startsWith("rules") ? "Rules" : x);
const SIGNALS = ["none", "possible", "clear"];
const REASONS = ["none", "job_loss", "reduced_income", "medical", "bereavement", "other"];

/** The note with every evidence span marked, coloured by the field it supports. */
const FRENCH = /\b(le|la|les|des|une|est|pas|avec|chez|famille|paiement|promesse|appel|client|pour|sur)\b/gi;

/** Text with the characters the source export lost (U+FFFD) made legible: in French notes the lost letter is almost
 * always "é", restored with a dotted underline; elsewhere a quiet placeholder. Same length, so quote offsets hold. */
function Legible({ text, french }: { text: string; french: boolean }) {
  if (!text.includes("\uFFFD")) return <>{text}</>;
  return (
    <>
      {text.split("\uFFFD").flatMap((part, i) =>
        i === 0
          ? [part]
          : [
              french ? (
                <span key={i} className="k-lost" title="Restored: this letter was lost in the source system's export">
                  é
                </span>
              ) : (
                <span key={i} className="k-lost gone" title="A character was lost in the source system's export">
                  ·
                </span>
              ),
              part,
            ],
      )}
    </>
  );
}

export function Highlighted({ note, ex }: { note: string; ex: TextExtraction }) {
  const french = (note.match(FRENCH) ?? []).length >= 2;
  const spans = FIELDS.flatMap((f) => {
    const e = ex[f.key].evidence;
    return e ? [{ start: e.char_start, end: e.char_end, f }] : [];
  })
    .sort((a, b) => a.start - b.start)
    .filter((s, i, all) => i === 0 || s.start >= all[i - 1].end); // overlapping quotes: keep the first
  const parts: React.ReactNode[] = [];
  let at = 0;
  spans.forEach((s, i) => {
    if (s.start > at) parts.push(<Legible key={`t${i}`} text={note.slice(at, s.start)} french={french} />);
    parts.push(
      <Tooltip key={i} content={s.f.label}>
        <mark className={`k-mark t-${s.f.tint}`}>
          <Legible text={note.slice(s.start, s.end)} french={french} />
        </mark>
      </Tooltip>,
    );
    at = s.end;
  });
  parts.push(<Legible key="end" text={note.slice(at)} french={french} />);
  return <p className="k-quote">{parts}</p>;
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

  const [open, setOpen] = useState(false);
  const hits = FIELDS.filter((f) => found(f.kind, value(f.key)));
  const garbled = item.note.includes("\uFFFD");
  const confirmed = !!ex.confirmed_by_agent_id;
  return (
    <div className="k-notecard">
      <div className="k-notecard-head">
        <span className="k-notecard-ico" aria-hidden>
          <FileTextIcon />
        </span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="k-notecard-title">Note {ex.source_id.replace(/^N-/, "")}</div>
          <div className="k-notecard-meta">
            {reader(ex.extractor)} · {new Date(ex.extracted_at).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}
          </div>
        </div>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={ex.confirmed_by_agent_id ?? "unconfirmed"} initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={spring}>
            {confirmed ? (
              <span className="k-cust-chip" data-tone="good">
                <CheckCircledIcon style={{ marginRight: 5 }} /> Confirmed
              </span>
            ) : (
              <span className="k-cust-chip" data-tone="warn">
                Needs confirmation
              </span>
            )}
          </motion.span>
        </AnimatePresence>
      </div>

      {item.note.trim() ? <Highlighted note={item.note} ex={ex} /> : <p className="k-quote k-notecard-none">The note text is not stored for this record; its extracted values are below.</p>}
      {garbled && <p className="k-notecard-warn">Characters lost in the source system&apos;s export are restored or marked (dotted).</p>}

      <div className="k-notecard-read">
        <span className="k-cust-h" style={{ margin: 0 }}>
          What was read
        </span>
        <div className="k-notecard-chips">
          {hits.length ? (
            hits.map((f) => {
              const conf = f.key in edits ? 1 : ex[f.key].confidence;
              return (
                <span key={f.key} className={`k-readchip t-${f.tint}`} data-edited={f.key in edits}>
                  <b>{f.label}</b> {shown(f.kind, value(f.key))}
                  <i className="tabular">{f.key in edits ? "edited" : `${Math.round(conf * 100)}%`}</i>
                </span>
              );
            })
          ) : (
            <span className="k-notecard-none">Nothing actionable found in this note.</span>
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="fields" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }} style={{ overflow: "hidden" }}>
            <div className="k-notecard-fields">
              {FIELDS.map((f) => {
                const v = value(f.key);
                const conf = f.key in edits ? 1 : ex[f.key].confidence;
                return (
                  <div key={f.key} className={`k-field t-${f.tint}`} data-edited={f.key in edits}>
                    <div className="k-field-head">
                      <span>{f.label}</span>
                      <Tooltip content={f.key in edits ? "Your edit" : "Model confidence"}>
                        <span className="tabular">{f.key in edits ? "edited" : `${Math.round(conf * 100)}%`}</span>
                      </Tooltip>
                    </div>
                    {f.kind === "bool" && <Switch size="1" checked={Boolean(v)} onCheckedChange={(c) => set(f.key, c)} color={f.key === "cease_request" ? "red" : undefined} aria-label={f.label} />}
                    {(f.kind === "signal" || f.kind === "reason") && (
                      <Select.Root size="1" value={String(v)} onValueChange={(x) => set(f.key, x)}>
                        <Select.Trigger aria-label={f.label} style={{ width: "100%" }} />
                        <Select.Content>
                          {(f.kind === "signal" ? SIGNALS : REASONS).map((o) => (
                            <Select.Item key={o} value={o}>
                              {humanize(o)}
                            </Select.Item>
                          ))}
                        </Select.Content>
                      </Select.Root>
                    )}
                    {f.kind === "amount" && (
                      <TextField.Root size="1" inputMode="decimal" placeholder="None" value={v == null ? "" : String(v)} onChange={(e) => set(f.key, e.target.value === "" ? null : e.target.value)} aria-label={f.label} />
                    )}
                    {f.kind === "date" && (
                      <TextField.Root size="1" type="date" value={v == null ? "" : String(v)} onChange={(e) => set(f.key, e.target.value === "" ? null : e.target.value)} aria-label={f.label} />
                    )}
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <Text as="p" size="1" color="red">
          {error}
        </Text>
      )}
      <div className="k-notecard-foot">
        <button className="k-text-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? <ChevronUpIcon /> : <ChevronDownIcon />} {open ? "Hide fields" : "Review all fields"}
        </button>
        <Flex gap="2" align="center">
          {changed && (
            <button className="k-tab" onClick={() => setEdits({})}>
              Undo edits
            </button>
          )}
          <button className="k-strong-btn" disabled={busy || (!changed && confirmed)} onClick={() => void save()}>
            {busy ? "Saving…" : changed ? "Save corrections" : confirmed ? "Confirmed" : "Confirm"}
          </button>
        </Flex>
      </div>
    </div>
  );
}

export function ExtractionPanel({ items, agentId, demo, onSaved }: { items: NoteExtraction[]; agentId: string; demo: boolean; onSaved: () => void }) {
  if (!items.length) return null;
  return (
    <Card size="3">
      <SectionTitle eyebrow="Notes" title="Extracted from notes" mb="1" aside={<span className="k-badge">{items.length}</span>} />
      <Text as="p" size="2" color="gray" mt="1" mb="4">
        Confirm or correct each value. A confirmed hardship signal sets hardship to confirmed; a confirmed stop request becomes
        a hard stop.
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
