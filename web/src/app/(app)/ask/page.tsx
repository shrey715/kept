"use client";

import { ExclamationTriangleIcon, MagicWandIcon, QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Code, Flex, Heading, Table, Text, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Rise, Stagger, spring } from "@/components/motion";
import { api, humanize, type AskResponse } from "@/lib/api";
import { useSession } from "@/lib/session";

const EXAMPLES = [
  "What is the promise kept rate by product for the last 90 days?",
  "What is the kept rate by gender?",
  "Which strategy worked best for unsecured loans in the last 90 days?",
  "Who approves a payment reduction?",
];

export default function AskPage() {
  const { me } = useSession();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ q: string; r: AskResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    if (!me || !question.trim()) return;
    setQ(question);
    setBusy(true);
    setError(null);
    try {
      setRes({ q: question, r: await api.ask(question, me) });
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
        <Text color="gray" size="2">Plain-English questions. Every answer shows its SQL, its tables and how fresh the data is.</Text>
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
                <Text as="p" size="5" className="serif" weight="medium">{r.narrative}</Text>
                {r.columns.length > 0 && (
                  <Table.Root mt="4" variant="surface" size="1">
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
                )}
                {r.citations.map((c) => (
                  <Card key={`${c.document_id}-${c.section}`} variant="surface" mt="3">
                    <Text weight="bold" size="2">{c.document_id} {c.section}</Text>
                    <Text size="1" color="gray"> · effective {c.effective_from}</Text>
                    <Text as="p" size="2" color="gray" mt="1">{c.snippet}</Text>
                  </Card>
                ))}
                {r.sql && (
                  <details style={{ marginTop: 16 }}>
                    <summary style={{ cursor: "pointer" }}><Text size="2" color="gray">Show SQL</Text></summary>
                    <Code variant="soft" size="2" style={{ display: "block", whiteSpace: "pre-wrap", padding: 12, marginTop: 8 }}>{r.sql}</Code>
                  </details>
                )}
                <Text as="p" size="1" color="gray" mt="3">
                  Tables: {r.tables_used.join(", ") || "none"}
                  {r.data_freshness && ` · data as of ${new Date(r.data_freshness).toLocaleDateString("en-CA", { dateStyle: "medium" })}`}
                </Text>
              </Card>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </Stagger>
  );
}
