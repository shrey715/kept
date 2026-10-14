"use client";

// Where an Ask answer comes from: numbered tags in the answer, a card per source, and a "Verify" view
// that opens the full source (POST /ask/source) with the cited passage highlighted, so nobody has to
// take the model's word for it.
import { CheckCircledIcon, ExclamationTriangleIcon, FileTextIcon, ReaderIcon, TableIcon } from "@radix-ui/react-icons";
import { Box, Button, Callout, Dialog, Flex, Spinner, Text } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";
import { api, type AskAnswer, type Citation, type SourceText } from "@/lib/api";
import { useSession } from "@/lib/session";
import { SectionTitle } from "./page-header";
import { inline, stripMarks } from "./rich-text";
import { SqlBlock } from "./sql-block";

const day = (d?: string | null) =>
  d ? new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString("en-CA", { dateStyle: "medium" }) : null;

function Tag({ n, muted, onClick }: { n: number; muted?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Source ${n}: verify`}
      style={{
        verticalAlign: "super", fontSize: "0.58em", lineHeight: 1, marginLeft: 3, padding: "3px 6px", border: "none",
        borderRadius: 999, cursor: "pointer", fontFamily: "var(--default-font-family)", fontWeight: 700,
        background: muted ? "var(--k-chip)" : "var(--k-red)", color: muted ? "var(--gray-11)" : "#fff",
      }}
    >
      {n}
    </button>
  );
}

/** The narrative, with each source it names underlined and tagged [n]; a source with no words in the text
 * (a call transcript) is tagged at the end. */
export function CitedText({ text, citations, onOpen }: { text: string; citations: Citation[]; onOpen: (c: Citation) => void }) {
  const used = citations.filter((c) => c.used);
  const named = used.filter((c) => c.mention);
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (;;) {
    const next = named
      .map((c) => ({ c, i: text.indexOf(c.mention!, at) }))
      .filter((m) => m.i >= 0)
      .sort((a, b) => a.i - b.i)[0];
    if (!next) break;
    const end = next.i + next.c.mention!.length;
    parts.push(...inline(text.slice(at, next.i), `t${at}`));
    parts.push(
      <span key={next.i} style={{ textDecoration: "underline dotted var(--accent-8)", textUnderlineOffset: 3 }}>
        {inline(text.slice(next.i, end), `m${next.i}`)}
        <Tag n={next.c.ref ?? 0} onClick={() => onOpen(next.c)} />
      </span>,
    );
    at = end;
  }
  parts.push(...inline(text.slice(at), `t${at}`));
  used.filter((c) => !c.mention).forEach((c) => parts.push(<Tag key={`end-${c.ref}`} n={c.ref ?? 0} onClick={() => onOpen(c)} />));
  return (
    <Text as="p" size="5" style={{ whiteSpace: "pre-line", fontFamily: "var(--heading-font-family)", letterSpacing: "-0.015em", lineHeight: 1.45 }}>
      {parts}
    </Text>
  );
}

function SourceCard({ c, muted, onOpen }: { c: Citation; muted?: boolean; onOpen: (c: Citation) => void }) {
  const transcript = c.kind === "transcript";
  return (
    <div className="k-source" data-muted={muted}>
      <span className="k-source-n" data-muted={muted}>
        {c.ref ?? "·"}
      </span>
      <Box style={{ flex: 1, minWidth: 0 }}>
        <Flex gap="2" align="center" wrap="wrap">
          <span className="k-badge" style={{ gap: 6 }}>
            {transcript ? <ReaderIcon /> : <FileTextIcon />}
            {transcript ? `Call ${c.source_id ?? ""}` : c.document_id}
          </span>
          {!transcript && c.section && <span className="k-badge">{c.section}</span>}
          <Text size="1" color="gray">
            {transcript ? `call on ${day(c.effective_from)}` : `in force from ${day(c.effective_from)}`}
          </Text>
        </Flex>
        <blockquote className="k-quote">
          {transcript ? `Summarised from the redacted transcript: ${c.snippet}` : inline(c.snippet.replace(/^#+\s*/gm, "").replace(/\s*\n\s*/g, " "), "s")}
        </blockquote>
      </Box>
      <button className="k-strong-btn" style={{ height: 34, padding: "0 14px", fontSize: 12 }} onClick={() => onOpen(c)}>
        <CheckCircledIcon /> Verify
      </button>
    </div>
  );
}

/** Every source behind an answer: what it relied on first, what search also found (folded), and for
 * a data answer the query, its tables and how fresh they are. */
export function Sources({ r, onOpen }: { r: AskAnswer; onOpen: (c: Citation) => void }) {
  const used = r.citations.filter((c) => c.used);
  const others = r.citations.filter((c) => !c.used);
  if (!r.sql && r.citations.length === 0) return null;
  return (
    <Box mt="5" pt="4" style={{ borderTop: "1px solid var(--k-line)" }}>
      <SectionTitle
        eyebrow="Sources"
        title="Where this answer comes from"
        mb="3"
        aside={
          <span className="k-badge" style={{ height: 28, padding: "0 10px", borderRadius: 999 }}>
            {r.sql ? "computed from the warehouse" : `${used.length} relied on${others.length ? ` · ${others.length} also found` : ""}`}
          </span>
        }
      />
      {r.sql && (
        <div className="k-source">
          <span className="k-source-n">
            <TableIcon />
          </span>
          <Box style={{ flex: 1, minWidth: 0 }}>
            <Flex gap="2" align="center" wrap="wrap">
              {(r.tables_used.length ? r.tables_used : ["query"]).map((t) => (
                <span key={t} className="k-badge" style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}>
                  {t}
                </span>
              ))}
              <span className="k-badge">
                {r.rows.length} row{r.rows.length === 1 ? "" : "s"}
              </span>
              {r.data_freshness && <span className="k-badge">data as of {day(r.data_freshness)}</span>}
            </Flex>
            <Text as="p" size="1" color="gray" mt="2">
              Read-only SQL, checked by the SQL guard before it ran. Every number above comes from it.
            </Text>
            <SqlBlock sql={r.sql} label="The query" />
          </Box>
        </div>
      )}
      {!r.sql && used.length === 0 && others.length > 0 && (
        <Callout.Root color="amber" size="1" mt="2">
          <Callout.Icon><ExclamationTriangleIcon /></Callout.Icon>
          <Callout.Text>The answer doesn&apos;t name any of these sections. Check them before relying on it.</Callout.Text>
        </Callout.Root>
      )}
      {used.map((c) => <SourceCard key={c.ref} c={c} onOpen={onOpen} />)}
      {others.length > 0 && (
        <details style={{ marginTop: 8 }} open={used.length === 0}>
          <summary style={{ cursor: "pointer" }}><Text size="1" color="gray">Also found by search, not relied on ({others.length})</Text></summary>
          {others.map((c) => <SourceCard key={c.ref} c={c} muted onOpen={onOpen} />)}
        </details>
      )}
    </Box>
  );
}

/** Spans to mark: the cited passage of a document; for a transcript, wherever the summary's figures appear. */
function spans(c: Citation, s: SourceText): [number, number][] {
  if (s.highlight_start != null && s.highlight_end != null) return [[s.highlight_start, s.highlight_end]];
  if (c.kind !== "transcript") return [];
  const figures = [...new Set(c.snippet.match(/\$?\d[\d,]*(?:\.\d+)?/g) ?? [])].filter((f) => f.replace("$", "").length >= 2);
  return figures
    .flatMap((f) => [...s.text.matchAll(new RegExp(f.replace(/[$.]/g, "\\$&"), "g"))].map((m): [number, number] => [m.index!, m.index! + f.length]))
    .sort((a, b) => a[0] - b[0])
    .filter((x, i, all) => i === 0 || x[0] >= all[i - 1][1]);
}

function Marked({ c, s }: { c: Citation; s: SourceText }) {
  const first = useRef<HTMLElement>(null);
  useEffect(() => {
    first.current?.scrollIntoView({ block: "center" });
  }, [s]);
  const { plain: text, at: to } = stripMarks(s.text); // shown without markdown markers; spans move with it
  const parts: React.ReactNode[] = [];
  let at = 0;
  spans(c, s).map(([a, b]): [number, number] => [to(a), to(b)]).forEach(([a, b], i) => {
    parts.push(text.slice(at, a));
    parts.push(
      <mark key={a} ref={i === 0 ? first : undefined} style={{ background: "var(--accent-a4)", color: "inherit", borderRadius: 3, padding: "0 2px", boxShadow: "inset 0 -2px 0 var(--accent-8)" }}>
        {text.slice(a, b)}
      </mark>,
    );
    at = b;
  });
  parts.push(text.slice(at));
  return (
    <Box style={{ maxHeight: "55vh", overflowY: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7, padding: 12, borderRadius: 6, background: "var(--gray-a2)" }}>
      <Text size="2">{parts}</Text>
    </Box>
  );
}

/** [open(citation), the dialog to render once]: fetches the source and shows it with the passage marked. */
export function useVerify(): [(c: Citation) => void, React.ReactNode] {
  const { me } = useSession();
  const [c, setC] = useState<Citation | null>(null);
  const [src, setSrc] = useState<SourceText | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function open(next: Citation) {
    if (!me) return;
    setC(next);
    setSrc(null);
    setErr(null);
    api.askSource(next, me).then(setSrc, (e: Error) => setErr(e.message));
  }

  const found = src && src.highlight_start != null;
  const dialog = (
    <Dialog.Root open={c !== null} onOpenChange={(o) => !o && setC(null)}>
      <Dialog.Content maxWidth="760px">
        {c && (
          <>
            <Dialog.Title>{c.kind === "transcript" ? src?.title ?? "Call transcript" : `${c.document_id} ${c.section}`}</Dialog.Title>
            <Dialog.Description size="2" color="gray" mb="3">
              Source [{c.ref}] behind the answer, opened from the indexed original.
            </Dialog.Description>
            {err && <Callout.Root color="red" mb="3"><Callout.Text>Couldn&apos;t open the source: {err}</Callout.Text></Callout.Root>}
            {!src && !err && <Flex justify="center" p="6"><Spinner size="3" /></Flex>}
            {src && (
              <>
                <Callout.Root color={c.kind === "transcript" ? "gray" : found ? "green" : "amber"} size="1" mb="3">
                  <Callout.Icon>{found || c.kind === "transcript" ? <CheckCircledIcon /> : <ExclamationTriangleIcon />}</Callout.Icon>
                  <Callout.Text>
                    {c.kind === "transcript"
                      ? "The redacted transcript the summary was written from. The figures it quotes are highlighted."
                      : found
                        ? `Quote found word for word in ${src.title}, in force ${day(src.effective_from)} – ${src.effective_to ? day(src.effective_to) : "today"}.`
                        : `This passage isn't in the indexed ${src.title} any more. Treat the answer as unverified.`}
                  </Callout.Text>
                </Callout.Root>
                <Marked c={c} s={src} />
              </>
            )}
            <Flex justify="end" mt="4">
              <Dialog.Close><Button variant="soft" color="gray">Close</Button></Dialog.Close>
            </Flex>
          </>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
  return [open, dialog];
}
