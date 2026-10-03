"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Field, Panel, inputClass } from "@/components/ui";
import { useRecentCases } from "@/lib/recent";

export default function Home() {
  const router = useRouter();
  const [caseId, setCaseId] = useState("");
  const { recent } = useRecentCases();

  return (
    <div className="grid gap-6 md:grid-cols-[2fr_1fr]">
      <Panel title="Open a case">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (caseId.trim()) router.push(`/cases/${encodeURIComponent(caseId.trim())}`);
          }}
        >
          <Field label="Case ID">
            <input
              className={`${inputClass} w-64 font-mono`}
              placeholder="CS-2026-302680"
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              autoFocus
            />
          </Field>
          <Button type="submit" disabled={!caseId.trim()}>
            Open
          </Button>
        </form>
        <p className="mt-4 max-w-prose text-sm text-muted">
          The card shows what to do next, why, and the safety checks it passed. Nothing is sent until a person
          releases it.
        </p>
      </Panel>
      <Panel title="Recent cases">
        {recent.length ? (
          <ul className="grid gap-1">
            {recent.map((id) => (
              <li key={id}>
                <Link className="font-mono text-sm text-accent hover:underline" href={`/cases/${encodeURIComponent(id)}`}>
                  {id}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Cases you open appear here.</p>
        )}
      </Panel>
    </div>
  );
}
