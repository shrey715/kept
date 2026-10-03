"use client";

import { ArrowRightIcon } from "@radix-ui/react-icons";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { humanize, when, type AuditEvent, type AuditKind } from "@/lib/api";
import { spring } from "./motion";

const KIND: Partial<Record<AuditKind, { color: "ruby" | "grass" | "amber" | "plum" | "gray" | "iris" | "cyan"; label: string }>> = {
  recommendation: { color: "iris", label: "Recommendation" },
  release: { color: "grass", label: "Release decision" },
  override: { color: "plum", label: "Override" },
  hardship_change: { color: "amber", label: "Hardship change" },
  proposal_cancelled: { color: "gray", label: "Proposal cancelled" },
  ask_query: { color: "cyan", label: "Ask" },
  llm_call: { color: "cyan", label: "LLM call" },
};

function summary(e: AuditEvent): ReactNode {
  const p = e.payload as Record<string, unknown>;
  if (e.kind === "recommendation")
    return p.action ? `${humanize(String(p.action))} · ${p.tier} tier · model ${p.model_version}` : String(p.no_action_reason ?? "no action");
  if (e.kind === "release" || e.kind === "override") return String(p.reason ?? "");
  if (e.kind === "hardship_change")
    return (
      <>
        {String(p.from)} <ArrowRightIcon style={{ verticalAlign: "-2px" }} aria-label="to" /> {String(p.to)} ({String(p.source)})
      </>
    );
  if (e.kind === "proposal_cancelled") return String(p.reason ?? "");
  return Object.entries(p).slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(" · ");
}

export function AuditTimeline({ events, showCase }: { events: AuditEvent[]; showCase?: boolean }) {
  if (!events.length) return <Text color="gray" size="2">Nothing logged yet.</Text>;
  return (
    <Box position="relative" pl="5">
      <Box position="absolute" top="2" bottom="2" left="0" style={{ width: 2, marginLeft: 5, background: "var(--gray-a4)", borderRadius: 1 }} />
      <Flex direction="column" gap="4">
        {events.map((e, i) => {
          const k = KIND[e.kind] ?? { color: "gray" as const, label: humanize(e.kind) };
          const p = e.payload as Record<string, unknown>;
          return (
            <motion.div key={e.event_id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: Math.min(i, 15) * 0.04 }} style={{ position: "relative" }}>
              <Box position="absolute" style={{ left: -21, top: 5, width: 10, height: 10, borderRadius: 999, background: `var(--${k.color}-9)`, boxShadow: "0 0 0 3px var(--color-panel-solid)" }} />
              <Flex gap="2" align="center" wrap="wrap">
                <Badge color={k.color} variant="soft">{k.label}</Badge>
                {e.kind === "release" && p.released === true && <Badge color="grass" variant="solid">released</Badge>}
                {e.kind === "release" && p.status === "approved" && <Badge color="amber" variant="outline">1 of 2</Badge>}
                <Text size="1" color="gray" className="tabular">{when(e.at, { month: "short", day: "numeric", second: "2-digit" })}</Text>
              </Flex>
              <Text as="p" size="2" mt="1">{summary(e)}</Text>
              <Text as="p" size="1" color="gray">
                {e.actor_id}{e.actor_role ? ` (${humanize(e.actor_role)})` : ""}
                {showCase && (p.case_id || e.subject_id) ? ` · ${String(p.case_id ?? e.subject_id)}` : ""}
              </Text>
            </motion.div>
          );
        })}
      </Flex>
    </Box>
  );
}
