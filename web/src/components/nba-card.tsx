"use client";

import { ExclamationTriangleIcon, LockClosedIcon } from "@radix-ui/react-icons";
import { Badge, Box, Callout, Card, DataList, Flex, Grid, Heading, Text, Tooltip } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { ACTION_LABEL, money, pct, when, type Action, type NBACard } from "@/lib/api";
import { TierBadge } from "./bits";
import { CountUp, Meter, spring } from "./motion";

/** The left column of the case page: what to do, why, and how likely it is to work. */
export function NbaCard({ card, balance }: { card: NBACard; balance?: number }) {
  const p = card.proposal;
  const [compare, setCompare] = useState<Action[]>([]);
  const toggle = (a: Action) => setCompare((c) => (c.includes(a) ? c.filter((x) => x !== a) : [...c, a].slice(-2)));
  const chosen = compare.map((a) => card.probabilities.find((x) => x.action === a)).filter((x) => x !== undefined);
  const pair = chosen.length === 2 ? chosen : null;
  const pairDiff = pair ? pair[0].p_paid_14d - pair[1].p_paid_14d : 0;
  const wait = card.probabilities.find((a) => a.action === "wait")?.p_paid_14d;
  const maxPts = Math.max(1, ...card.reasons.map((r) => r.contribution_pts));

  return (
    <Flex direction="column" gap="4">
      <AnimatePresence initial={false}>
        {card.hard_stop?.blocked && (
          <motion.div key="stop" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
            <Callout.Root color="gray" variant="surface" size="2">
              <Callout.Icon>
                <LockClosedIcon />
              </Callout.Icon>
              <Callout.Text>
                <Text weight="bold">Hard stop. </Text>
                {card.hard_stop.rule_card}
              </Callout.Text>
            </Callout.Root>
          </motion.div>
        )}
        {card.hardship_banner && (
          <motion.div
            key="hardship"
            initial={{ opacity: 0, y: -10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, height: 0 }}
            transition={spring}
          >
            <Callout.Root color="amber" variant="surface" size="2">
              <Callout.Icon>
                <ExclamationTriangleIcon />
              </Callout.Icon>
              <Callout.Text>{card.hardship_banner.split(" Eligible programmes: ")[0]}</Callout.Text>
              {card.hardship_banner.includes(" Eligible programmes: ") && (
                <Flex gap="2" wrap="wrap" mt="1">
                  <Text size="1" weight="bold" style={{ color: "var(--amber-11)" }}>ELIGIBLE PROGRAMMES</Text>
                  {card.hardship_banner.split(" Eligible programmes: ")[1].replace(/\.$/, "").split("; ").map((name, i) => (
                    <motion.span key={name} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: 0.1 + i * 0.06 }}>
                      <Badge color="amber" variant="surface" radius="full">{name}</Badge>
                    </motion.span>
                  ))}
                </Flex>
              )}
            </Callout.Root>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.div layout transition={spring}>
        <Card size="3" style={{ overflow: "hidden" }}>
          <Flex align="center" gap="2" wrap="wrap">
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span key={p?.tier ?? "none"} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} transition={spring}>
                {p ? <TierBadge tier={p.tier} /> : <Badge color="gray" variant="soft" radius="full">No action</Badge>}
              </motion.span>
            </AnimatePresence>
            {p?.is_legacy_strategy && <Badge variant="outline" color="gray" radius="full">Old strategy</Badge>}
          </Flex>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={card.headline} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
              <Heading size="8" mt="3" style={{ lineHeight: 1.1 }}>
                {card.headline}
              </Heading>
              <Text as="p" color="gray" size="2" mt="2">
                {p
                  ? `${ACTION_LABEL[p.action]} · approve by ${when(p.expires_at)}`
                  : !card.hard_stop?.blocked && card.no_action_reason}
              </Text>
            </motion.div>
          </AnimatePresence>
          {p?.sizing && (
            <Box mt="5" p="4" style={{ background: "var(--accent-a2)", borderRadius: "var(--radius-4)" }}>
              <Grid columns={{ initial: "2", sm: "4" }} gap="4">
                <Stat label={p.sizing.installments > 1 ? "Per payment" : "Promise"}>
                  <CountUp value={Number(p.sizing.amount)} format={(n) => money(n)} />
                </Stat>
                <Stat label="Payments">{p.sizing.installments}</Stat>
                <Stat label="First due">
                  {new Date(`${p.sizing.due_date}T12:00:00`).toLocaleDateString("en-CA", { month: "short", day: "numeric" })}
                </Stat>
                <Stat label="Spare cash / period">~{money(p.sizing.spare_cash_estimate)}</Stat>
              </Grid>
              {card.sizing_text && (
                <Text as="p" size="2" color="gray" mt="3">
                  {card.sizing_text}
                </Text>
              )}
            </Box>
          )}
        </Card>
      </motion.div>

      {card.reasons.length > 0 && (
        <motion.div layout transition={spring}>
          <Card size="3">
            <Heading size="4" mb="4">Why this action</Heading>
            <Flex direction="column" gap="4">
              {card.reasons.map((r, i) => (
                <motion.div key={r.feature} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ ...spring, delay: 0.1 + i * 0.08 }}>
                  <Flex justify="between" gap="4" mb="2">
                    <Text size="3">{r.sentence}</Text>
                    <Text size="2" color="gray" className="tabular" style={{ whiteSpace: "nowrap" }}>
                      +{r.contribution_pts.toFixed(1)} pts
                    </Text>
                  </Flex>
                  <Meter value={r.contribution_pts} max={maxPts} delay={0.15 + i * 0.08} />
                </motion.div>
              ))}
            </Flex>
          </Card>
        </motion.div>
      )}

      {card.probabilities.length > 0 && (
        <motion.div layout transition={spring}>
          <Card size="3">
            <Heading size="4">Chance of a payment within 14 days</Heading>
            {wait !== undefined && (
              <Text as="p" size="2" color="gray" mt="1" mb="4">
                The tick marks doing nothing ({pct(wait)}). Hover a bar for detail; click two to compare.
              </Text>
            )}
            <Flex direction="column" gap="1">
              <AnimatePresence initial={false}>
                {card.probabilities.map((a, i) => {
                  const lift = wait !== undefined ? a.p_paid_14d - wait : 0;
                  const picked = compare.includes(a.action);
                  return (
                    <motion.div
                      key={a.action}
                      layout
                      initial={{ opacity: 0, x: 12 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -24, height: 0 }}
                      transition={spring}
                    >
                      <Tooltip
                        content={`${pct(a.p_paid_14d)} chance · ${lift >= 0 ? "+" : ""}${Math.round(lift * 100)} pts over doing nothing${
                          balance ? ` · ≈ ${money(Math.max(lift, 0) * balance)} expected` : ""
                        }`}
                      >
                        <motion.button
                          onClick={() => toggle(a.action)}
                          whileHover={{ x: 3 }}
                          aria-pressed={picked}
                          style={{
                            all: "unset", cursor: "pointer", display: "block", width: "100%", padding: "6px 8px", borderRadius: 8,
                            background: picked ? "var(--accent-a3)" : "transparent", boxSizing: "border-box",
                          }}
                        >
                          <Grid columns="11rem 1fr 3rem" gap="3" align="center">
                            <Text size="2" weight={i === 0 ? "bold" : "regular"} color={i === 0 ? undefined : "gray"}>
                              {ACTION_LABEL[a.action]}
                            </Text>
                            <Meter value={a.p_paid_14d} muted={i !== 0 && !picked} tick={a.action !== "wait" ? wait : undefined} delay={0.05 * i} />
                            <Text size="2" align="right" className="tabular" weight={i === 0 ? "bold" : "regular"}>
                              {pct(a.p_paid_14d)}
                            </Text>
                          </Grid>
                        </motion.button>
                      </Tooltip>
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </Flex>
            <AnimatePresence>
              {pair && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
                  <Box mt="3" p="3" style={{ background: "var(--gray-a2)", borderRadius: "var(--radius-3)" }}>
                    <Text size="2">
                      <Text weight="bold">{ACTION_LABEL[pair[0].action]}</Text> vs <Text weight="bold">{ACTION_LABEL[pair[1].action]}</Text>:{" "}
                      {pair[0].action === pair[1].action ? "" : `${ACTION_LABEL[pairDiff >= 0 ? pair[0].action : pair[1].action]} is ${Math.abs(Math.round(pairDiff * 100))} pts more likely to bring a payment`}
                      {balance ? ` (≈ ${money(Math.abs(pairDiff) * balance)} on ${money(balance)} at risk).` : "."}
                    </Text>
                  </Box>
                </motion.div>
              )}
            </AnimatePresence>
          </Card>
        </motion.div>
      )}
      {card.similar_cases_text && <Text size="2" color="gray">{card.similar_cases_text}</Text>}
    </Flex>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box>
      <Text as="div" size="1" color="gray" weight="medium">{label}</Text>
      <Text as="div" size="6" weight="bold" className="serif tabular">{children}</Text>
    </Box>
  );
}

export function Checks({ card }: { card: NBACard }) {
  if (!card.checks.length) return null;
  return (
    <DataList.Root size="2" orientation={{ initial: "vertical", sm: "horizontal" }}>
      {card.checks.map((c, i) => (
        <DataList.Item key={c.check}>
          <DataList.Label minWidth="120px">
            <Flex align="center" gap="2">
              <motion.span
                initial={{ scale: 0, rotate: -45 }}
                animate={{ scale: 1, rotate: 0 }}
                transition={{ ...spring, delay: 0.2 + i * 0.1 }}
                style={{ color: c.passed ? "var(--grass-11)" : "var(--red-11)", fontWeight: 700 }}
                aria-hidden
              >
                {c.passed ? "✓" : "✕"}
              </motion.span>
              <span style={{ textTransform: "capitalize" }}>{c.check.replaceAll("_", " ")}</span>
              <span className="rt-sr-only" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
                {c.passed ? "passed" : "failed"}
              </span>
            </Flex>
          </DataList.Label>
          <DataList.Value>{c.detail}</DataList.Value>
        </DataList.Item>
      ))}
    </DataList.Root>
  );
}
