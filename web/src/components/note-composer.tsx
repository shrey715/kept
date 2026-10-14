"use client";

import { ChatBubbleIcon, CheckIcon, LockClosedIcon, PlusIcon } from "@radix-ui/react-icons";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { SectionTitle } from "./page-header";

/** Phrases agents write most often: one click adds them to the note. */
const QUICK = [
  "Customer reports reduced hours at work.",
  "Customer promised to pay on payday.",
  "Customer disputes the balance.",
  "Customer asked for a callback after 18:00.",
  "Customer asked us to stop calling.",
];
const STEPS = ["Redacting personal data", "Reading the note", "Updating the recommendation"];
const MAX = 2000;

/** Add a note to the case: it is redacted, analysed for hardship, promises, disputes and cease requests, and the
 * recommendation is refreshed. Ctrl/⌘ + Enter saves. */
export function NoteComposer({ value, onChange, onSave, saving, demo }: { value: string; onChange: (v: string) => void; onSave: () => void; saving: boolean; demo: boolean }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!saving) return;
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1400);
    return () => {
      clearInterval(t);
      setStep(0);
    };
  }, [saving]);
  const add = (q: string) => onChange(value.trim() ? `${value.trim()} ${q}` : q);
  const ready = value.trim().length > 0 && !saving;
  return (
    <div className="k-card k-note" style={{ padding: 22 }}>
      <SectionTitle
        eyebrow="Notes"
        title="Add a note"
        icon={<ChatBubbleIcon />}
        mb="3"
        aside={
          <span className="k-note-badge">
            <LockClosedIcon /> Redacted before analysis
          </span>
        }
      />
      <div className="k-note-box" data-busy={saving}>
        <textarea
          value={value}
          maxLength={MAX}
          rows={3}
          disabled={saving}
          placeholder="Summarise the conversation: circumstances, commitments, requests."
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && ready) {
              e.preventDefault();
              onSave();
            }
          }}
          aria-label="Note"
        />
        <div className="k-note-bar">
          <div className="k-note-quick">
            {QUICK.map((q) => (
              <button key={q} type="button" onClick={() => add(q)} disabled={saving}>
                <PlusIcon /> {q.replace(/^Customer /, "").replace(/\.$/, "")}
              </button>
            ))}
          </div>
          <span className="k-note-count tabular">
            {value.length}/{MAX}
          </span>
        </div>
      </div>
      <div className="k-note-foot">
        <AnimatePresence mode="wait" initial={false}>
          {saving ? (
            <motion.ol key="steps" className="k-note-steps" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              {STEPS.map((s, i) => (
                <li key={s} data-state={i < step ? "done" : i === step ? "now" : "next"}>
                  <span className="dot">{i < step ? <CheckIcon /> : null}</span>
                  {s}
                </li>
              ))}
            </motion.ol>
          ) : (
            <motion.p key="hint" className="k-note-hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {demo
                ? "Demo mode reads notes with simple rules. Example: “Customer says shifts were cut at the plant.”"
                : "The note is checked for hardship, promises, disputes and cease requests, and the recommendation is updated."}
            </motion.p>
          )}
        </AnimatePresence>
        <button className="k-strong-btn" onClick={onSave} disabled={!ready}>
          {saving ? "Saving…" : "Save note"}
          <kbd className="k-note-kbd">Ctrl ↵</kbd>
        </button>
      </div>
    </div>
  );
}
