"use client";

import { ExclamationTriangleIcon, MagicWandIcon, QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Flex, Heading, Table, Tabs, Text, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { AnswerChart } from "@/components/answer-chart";
import { CitedText, Sources, useVerify } from "@/components/citations";
import { Rise, Stagger, spring } from "@/components/motion";
import { api, humanize, type AskResponse, type ChartChoice } from "@/lib/api";
import { useSession } from "@/lib/session";

// released benchmark questions the Ask gets right on the dev split, one per path (metric, policy, comparison, guardrail)
const EXAMPLES = [
  "What is the average days past due of open cases by queue?",
  "How many collections cases are open today, by current bucket?",
  "Among randomised cases, compare the promise-kept rate of the champion strategy with challenger_A and challenger_B.",
  "How many call attempts can we make on a mid-stage account in a week?",
  "List the gender and marital status of customers who broke a promise last month.",
];

export default function AskPage() {
  const { me } = useSession();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ q: string; r: AskResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chart, setChart] = useState<ChartChoice | null>(null); // the Chart tab; null = table only
  const [verify, verifyDialog] = useVerify();

  async function ask(question: string) {
    if (!me || !question.trim()) return;
    setQ(question);
    setBusy(true);
    setError(null);
    try {
      setChart(null);
      const r = await api.ask(question, me);
      setRes({ q: question, r });
      if (r.kind === "answer" && r.rows.length > 0) {
        // the chart is extra: if picking one fails, the answer and its table still stand
        api.chart({ question: r.question, sql: r.sql ?? null, columns: r.columns, rows: r.rows }, me).then(
          (c) => setChart(c.option.kind === "table" ? null : c),
          () => setChart(null),
        );
      }
    } catch (e) {
      setError((e as Error).message);
      setRes(null);
    } finally {
      setBusy(false);
    }
  }

  const r = res?.r;
  return (
    <Stagger>
      <Rise>
        <Heading size="8">Collections Ask</Heading>
        <Text color="gray" size="2">Plain-English questions. Every answer shows where it came from: the SQL and tables behind a number, or the policy section behind a rule, one click from the original.</Text>
      </Rise>
      <Rise>
        <Card size="3" mt="5">
          <form onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
            <Flex gap="3">
              <TextField.Root size="3" style={{ flex: 1 }} placeholder="Ask about metrics, cases or policy" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question">
                <TextField.Slot><MagicWandIcon /></TextField.Slot>
              </TextField.Root>
              <Button size="3" loading={busy} disabled={!q.trim()}>Ask</Button>
            </Flex>
          </form>
          <Flex gap="2" mt="3" wrap="wrap">
            {EXAMPLES.map((e) => (
              <motion.div key={e} whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}>
                <Button size="1" variant="soft" color="gray" radius="full" onClick={() => void ask(e)}>{e}</Button>
              </motion.div>
            ))}
          </Flex>
        </Card>
      </Rise>

      <AnimatePresence mode="wait">
        {error && (
          <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <Callout.Root color="red" mt="4"><Callout.Text>Ask failed: {error}</Callout.Text></Callout.Root>
          </motion.div>
        )}
        {res && r && (
          <motion.div key={res.q} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={spring}>
            {r.kind === "refusal" && (
              <Callout.Root color="amber" size="3" mt="4">
                <Callout.Icon><ExclamationTriangleIcon /></Callout.Icon>
                <Callout.Text>
                  <Text weight="bold">{r.message}</Text>
                  <br />
                  <Text size="1" color="gray">Refused: {humanize(r.reason)}</Text>
                </Callout.Text>
                {r.suggestion && (
                  <Box>
                    <Button size="1" variant="soft" onClick={() => void ask(r.suggestion!.replace(/^Try:\s*/, ""))}>{r.suggestion}</Button>
                  </Box>
                )}
              </Callout.Root>
            )}
            {r.kind === "clarification" && (
              <Callout.Root color="gray" size="3" mt="4">
                <Callout.Icon><QuestionMarkCircledIcon /></Callout.Icon>
                <Callout.Text>{r.question}</Callout.Text>
              </Callout.Root>
            )}
            {r.kind === "answer" && (
              <Card size="3" mt="4">
                <Flex gap="2" wrap="wrap" mb="3">
                  {[r.intent.kind, r.intent.metric_id, ...Object.entries(r.intent.filters ?? {}).map(([k, v]) => `${k}: ${String(v)}`), ...(r.intent.group_by ?? []).map((g) => `by ${g}`)]
                    .filter(Boolean)
                    .map((c, i) => (
                      <motion.span key={String(c)} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} transition={{ ...spring, delay: i * 0.06 }}>
                        <Badge size="2" variant="soft" radius="full">{String(c)}</Badge>
                      </motion.span>
                    ))}
                </Flex>
                <CitedText text={r.narrative} citations={r.citations} onOpen={verify} />
                {r.columns.length > 0 && (
                  <Tabs.Root key={res.q + (chart ? "-chart" : "")} defaultValue={chart ? "chart" : "table"} mt="4">
                    <Tabs.List size="1">
                      {chart && <Tabs.Trigger value="chart">Chart</Tabs.Trigger>}
                      <Tabs.Trigger value="table">Table</Tabs.Trigger>
                    </Tabs.List>
                    {chart && (
                      <Tabs.Content value="chart">
                        <Box pt="3">
                          <AnswerChart option={chart.option} columns={r.columns} rows={r.rows} />
                          <Text as="p" size="1" color="gray" mt="1">
                            {chart.source === "llm" ? "Chart picked by the model from the options the data supports" : "Chart picked by rules from the data's shape"}
                          </Text>
                        </Box>
                      </Tabs.Content>
                    )}
                    <Tabs.Content value="table">
                      <Box pt="3">
                        <Table.Root variant="surface" size="1">
                    <Table.Header>
                      <Table.Row>{r.columns.map((c) => <Table.ColumnHeaderCell key={c}>{c}</Table.ColumnHeaderCell>)}</Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {r.rows.slice(0, 100).map((row, i) => (
                        <motion.tr key={i} className="rt-TableRow" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { delay: 0.1 + i * 0.04 } }}>
                          {row.map((v, j) => <Table.Cell key={j} className="tabular">{v == null ? "—" : String(v)}</Table.Cell>)}
                        </motion.tr>
                      ))}
                    </Table.Body>
                  </Table.Root>
                      </Box>
                    </Tabs.Content>
                  </Tabs.Root>
                )}
                <Sources r={r} onOpen={verify} />
              </Card>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      {verifyDialog}
    </Stagger>
  );
}
