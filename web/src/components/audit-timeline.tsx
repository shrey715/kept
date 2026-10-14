"use client";

import {
  ArrowRightIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  CrossCircledIcon,
  DotFilledIcon,
  ExclamationTriangleIcon,
  MixIcon,
  Pencil2Icon,
  TargetIcon,
} from "@radix-ui/react-icons";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { humanize, when, type AuditEvent, type AuditKind } from "@/lib/api";
import { spring } from "./motion";

type Tint = "rose" | "butter" | "mint" | "ice" | "lilac";
const KIND: Partial<Record<AuditKind, { tint: Tint | null; icon: ReactNode; label: string }>> = {
  recommendation: { tint: "ice", icon: <TargetIcon />, label: "Recommendation" },
  release: { tint: "mint", icon: <CheckCircledIcon />, label: "Release decision" },
  override: { tint: "rose", icon: <Pencil2Icon />, label: "Override" },
  hardship_change: { tint: "butter", icon: <ExclamationTriangleIcon />, label: "Hardship change" },
  proposal_cancelled: { tint: null, icon: <CrossCircledIcon />, label: "Proposal cancelled" },
  ask_query: { tint: "lilac", icon: <ChatBubbleIcon />, label: "Ask" },
  llm_call: { tint: "lilac", icon: <MixIcon />, label: "LLM call" },
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
    <Box position="relative">
      {/* the chain: one hairline through every event's chip */}
      <Box position="absolute" top="3" bottom="3" style={{ left: 15, width: 2, background: "var(--k-line)", borderRadius: 1 }} />
      <Flex direction="column" gap="4">
        {events.map((e, i) => {
          const k = KIND[e.kind] ?? { tint: null, icon: <DotFilledIcon />, label: humanize(e.kind) };
          const p = e.payload as Record<string, unknown>;
          return (
            <motion.div
              key={e.event_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring, delay: Math.min(i, 15) * 0.04 }}
              style={{ position: "relative", display: "flex", gap: 14 }}
            >
              <span className={`k-ava${k.tint ? ` t-${k.tint}` : ""}`} aria-hidden style={{ position: "relative", boxShadow: "0 0 0 4px var(--card-background-color, var(--k-card))" }}>
                {k.icon}
              </span>
              <Box style={{ minWidth: 0, flex: 1 }}>
                <Flex gap="2" align="center" wrap="wrap">
                  <Text size="2" weight="medium" className={k.tint ? `t-${k.tint} k-tint-ink` : undefined}>
                    {k.label}
                  </Text>
                  {e.kind === "release" && p.released === true && <Badge color="grass" variant="solid" radius="full">released</Badge>}
                  {e.kind === "release" && p.status === "approved" && <Badge color="amber" variant="outline" radius="full">1 of 2</Badge>}
                  <Text size="1" color="gray" className="tabular">{when(e.at, { month: "short", day: "numeric", second: "2-digit" })}</Text>
                </Flex>
                <Text as="p" size="2" mt="1" style={{ overflowWrap: "anywhere" }}>{summary(e)}</Text>
                <Text as="p" size="1" color="gray">
                  {e.actor_id}{e.actor_role ? ` (${humanize(e.actor_role)})` : ""}
                  {showCase && (p.case_id || e.subject_id) ? ` · ${String(p.case_id ?? e.subject_id)}` : ""}
                </Text>
              </Box>
            </motion.div>
          );
        })}
      </Flex>
    </Box>
  );
}
