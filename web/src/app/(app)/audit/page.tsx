"use client";

import { PageHeader } from "@/components/page-header";
import { ReaderIcon } from "@radix-ui/react-icons";
import { Callout, Card, Select, Skeleton } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { AuditTimeline } from "@/components/audit-timeline";
import { Rise, Stagger } from "@/components/motion";
import { api, type AuditEvent, type AuditKind } from "@/lib/api";
import { useSession } from "@/lib/session";

const KINDS: [AuditKind | "all", string][] = [
  ["all", "Everything"],
  ["recommendation", "Recommendations"],
  ["release", "Release decisions"],
  ["override", "Overrides"],
  ["hardship_change", "Hardship changes"],
  ["proposal_cancelled", "Cancellations"],
  ["ask_query", "Ask queries"],
  ["llm_call", "LLM calls"],
];

export default function AuditPage() {
  const { me } = useSession();
  const [kind, setKind] = useState<AuditKind | "all">("all");
  const [events, setEvents] = useState<{ kind: string; list: AuditEvent[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    let live = true;
    api.audit(me, kind === "all" ? {} : { kind }).then(
      (list) => live && setEvents({ kind, list }),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [me, kind]);

  return (
    <Stagger>
      <Rise>
        <PageHeader
          icon={<ReaderIcon />}
          eyebrow="Audit trail"
          title="Activity log"
          sub="Every recommendation, decision and model call, in an append-only, hash-chained log."
          actions={
            <Select.Root size="3" value={kind} onValueChange={(v) => setKind(v as AuditKind | "all")}>
              <Select.Trigger />
              <Select.Content>
                {KINDS.map(([k, label]) => (
                  <Select.Item key={k} value={k}>
                    {label}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          }
        />
      </Rise>
      {error && (
        <Callout.Root color="red" mt="4">
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      )}
      <Rise>
        <Card size="3" mt="5">
          {events?.kind === kind ? <AuditTimeline key={kind} events={events.list} showCase /> : <Skeleton height="200px" />}
        </Card>
      </Rise>
    </Stagger>
  );
}
