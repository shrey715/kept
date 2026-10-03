"use client";

import { useState } from "react";
import { Banner, Button, Panel, inputClass } from "@/components/ui";
import { api, humanize, when, type AskResponse } from "@/lib/api";
import { useIdentity } from "@/lib/identity";

const EXAMPLES = [
  "What is the promise kept rate by product for the last 90 days?",
  "Which strategy worked best for unsecured loans in the last 90 days?",
  "Who approves a payment reduction?",
];

export default function AskPage() {
  const { me } = useIdentity();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    if (!question.trim()) return;
    setQ(question);
    setBusy(true);
    setError(null);
    setRes(null);
    try {
      setRes(await api.ask(question, me.userId, me.role));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4">
      <Panel title="Collections Ask">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(q);
          }}
        >
          <input
            aria-label="Question"
            className={`${inputClass} flex-1`}
            placeholder="Ask about metrics, cases or policy"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <Button type="submit" disabled={busy || !q.trim()}>
            {busy ? "Asking…" : "Ask"}
          </Button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((e) => (
            <button key={e} onClick={() => void ask(e)} className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:text-ink">
              {e}
            </button>
          ))}
        </div>
      </Panel>

      {error && <Banner tone="bad">Ask failed: {error}</Banner>}
      {res?.kind === "refusal" && (
        <Banner tone="warn">
          <p className="font-medium">{res.message}</p>
          {res.suggestion && (
            <button className="mt-2 text-sm text-accent hover:underline" onClick={() => void ask(res.suggestion!.replace(/^Try:\s*/, ""))}>
              {res.suggestion}
            </button>
          )}
          <p className="mt-1 text-xs text-muted">Reason: {humanize(res.reason)}</p>
        </Banner>
      )}
      {res?.kind === "clarification" && <Banner tone="info">{res.question}</Banner>}
      {res?.kind === "answer" && (
        <Panel>
          <div className="mb-3 flex flex-wrap gap-2">
            <Chip>{res.intent.kind}</Chip>
            {res.intent.metric_id && <Chip>{res.intent.metric_id}</Chip>}
            {Object.entries(res.intent.filters ?? {}).map(([k, v]) => (
              <Chip key={k}>
                {k} = {String(v)}
              </Chip>
            ))}
            {(res.intent.group_by ?? []).map((g) => (
              <Chip key={g}>by {g}</Chip>
            ))}
          </div>
          <p className="text-base">{res.narrative}</p>
          {res.columns.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    {res.columns.map((c) => (
                      <th key={c} className="px-2 py-1.5 font-medium">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {res.rows.slice(0, 100).map((row, i) => (
                    <tr key={i} className="border-b border-line last:border-0">
                      {row.map((v, j) => (
                        <td key={j} className="px-2 py-1.5 font-mono text-xs">
                          {v == null ? "—" : String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {res.citations.length > 0 && (
            <ul className="mt-4 grid gap-2">
              {res.citations.map((c) => (
                <li key={`${c.document_id}-${c.section}`} className="rounded-lg bg-soft p-3 text-sm">
                  <span className="font-medium">
                    {c.document_id} {c.section}
                  </span>
                  <span className="text-muted"> · effective {c.effective_from}</span>
                  <p className="mt-1 text-muted">{c.snippet}</p>
                </li>
              ))}
            </ul>
          )}
          {res.sql && (
            <details className="mt-4">
              <summary className="cursor-pointer text-sm text-muted">SQL</summary>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-soft p-3 font-mono text-xs">{res.sql}</pre>
            </details>
          )}
          <p className="mt-3 text-xs text-muted">
            Tables: {res.tables_used.join(", ") || "none"}
            {res.data_freshness && ` · data as of ${when(res.data_freshness)}`}
          </p>
        </Panel>
      )}
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full bg-soft px-2.5 py-0.5 font-mono text-xs">{children}</span>;
}
