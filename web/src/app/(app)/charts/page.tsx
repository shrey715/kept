"use client";

// Chart lab (#100): try the Ask's charts before they go on the Ask page. Ask a question (the real Ask), or
// load a sample result; POST /chart picks one of the charts the rows support (the LLM with the question, SQL
// and rows; the rules when there is no LLM) and this page draws it, with every other option one click away.
// Not linked from the nav on purpose: open /charts directly.
import { MagicWandIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Code, Flex, Heading, SegmentedControl, Table, Text, TextField } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { AnswerChart } from "@/components/answer-chart";
import { api, type ChartChoice } from "@/lib/api";
import { useSession } from "@/lib/session";

type Result = { question: string; sql: string | null; columns: string[]; rows: unknown[][]; narrative?: string };

const months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"];
const SAMPLES: Result[] = [
  {
    question: "What is the promise kept rate by product for the last 90 days?",
    sql: "SELECT product, kept_rate, n FROM ... (sample)",
    columns: ["product", "kept_rate", "n"],
    rows: [["credit_card", "0.5214", 9120], ["personal_loan", "0.4731", 4410], ["line_of_credit", "0.6102", 1202], ["auto_loan", "0.5577", 2390]],
  },
  {
    question: "How has the 30-day roll rate moved by month, cards vs loans?",
    sql: "SELECT month, product_family, roll_rate FROM ... (sample)",
    columns: ["month", "product_family", "roll_rate"],
    rows: months.flatMap((m, i) => [[m, "card", (0.47 + i * 0.006).toFixed(4)], [m, "loan", (0.41 - i * 0.004).toFixed(4)]]),
  },
  {
    question: "What is the average days past due of open cases?",
    sql: "SELECT avg(dpd) AS average_dpd FROM ... (sample)",
    columns: ["average_dpd"],
    rows: [["41.73"]],
  },
  {
    question: "Compare cost per contact and cost per right-party contact by channel",
    sql: "SELECT channel, cost_per_contact, cost_per_rpc FROM ... (sample)",
    columns: ["channel", "cost_per_contact", "cost_per_rpc"],
    rows: [["call", "1.75", "4.10"], ["sms", "0.01", "0.06"], ["email", "0.001", "0.02"], ["letter", "1.10", "3.80"]],
  },
  {
    question: "How many attempts did each agent make last week?",
    sql: "SELECT agent_id, attempts FROM ... (sample)",
    columns: ["agent_id", "attempts"],
    rows: Array.from({ length: 30 }, (_, i) => [`AG-${8300 + i}`, 40 + ((i * 37) % 60)]),
  },
];

export default function ChartLab() {
  const { me } = useSession();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [choice, setChoice] = useState<ChartChoice | null>(null);
  const [shown, setShown] = useState<string>("");

  async function chart(r: Result, show?: string) {
    if (!me) return;
    setRes(r);
    setChoice(null);
    const c = await api.chart({ question: r.question, sql: r.sql, columns: r.columns, rows: r.rows }, me);
    setChoice(c);
    setShown(show && c.options.some((o) => o.id === show) ? show : c.option.id);
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function ask(question: string) {
    if (!me || !question.trim()) return;
    const a = await api.ask(question, me);
    if (a.kind !== "answer") throw new Error(a.kind === "refusal" ? `Refused: ${a.message}` : `Clarification: ${a.question}`);
    if (a.columns.length === 0) throw new Error("The answer has no rows to chart (a policy or document answer).");
    await chart({ question, sql: a.sql ?? null, columns: a.columns, rows: a.rows, narrative: a.narrative });
  }

  // /charts?sample=N[&option=K] opens sample N (and shows option K) straight away: screenshots, shared test links.
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const n = Number(sp.get("sample") ?? NaN);
    if (!me || !Number.isInteger(n) || !SAMPLES[n] || res) return;
    const t = setTimeout(() => void run(() => chart(SAMPLES[n], sp.get("option") ?? undefined)), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  const opt = choice?.options.find((o) => o.id === shown) ?? choice?.option;
  return (
    <Box>
      <Heading size="8">Chart lab</Heading>
      <Text color="gray" size="2">
        Issue #100, not on the Ask page yet. The model sees the question, the SQL and the rows, and picks one of the charts the rows support; the drawing is
        fixed code. Every number comes from the rows.
      </Text>

      <Card size="3" mt="5">
        <form onSubmit={(e) => { e.preventDefault(); void run(() => ask(q)); }}>
          <Flex gap="3">
            <TextField.Root size="3" style={{ flex: 1 }} placeholder="Ask the real Ask a question, then chart the answer" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question">
              <TextField.Slot><MagicWandIcon /></TextField.Slot>
            </TextField.Root>
            <Button size="3" loading={busy} disabled={!q.trim()}>Ask and chart</Button>
          </Flex>
        </form>
        <Text as="div" size="1" color="gray" mt="3" mb="2">Or a sample result (no Ask call, only the chart pick):</Text>
        <Flex gap="2" wrap="wrap">
          {SAMPLES.map((s) => (
            <Button key={s.question} size="1" variant="soft" color="gray" radius="full" disabled={busy} onClick={() => void run(() => chart(s))}>{s.question}</Button>
          ))}
        </Flex>
      </Card>

      {error && <Callout.Root color="red" mt="4"><Callout.Text>{error}</Callout.Text></Callout.Root>}

      {res && choice && opt && (
        <Card size="3" mt="4">
          <Flex justify="between" align="start" gap="3" wrap="wrap" mb="3">
            <Box>
              <Heading size="4">{opt.title}</Heading>
              <Text size="1" color="gray">{res.question}</Text>
            </Box>
            <Badge size="2" color={choice.source === "llm" ? "violet" : "gray"} variant="soft">
              {choice.source === "llm" ? `picked by the model: option ${choice.option.id}` : `picked by the rules: option ${choice.option.id}`}
            </Badge>
          </Flex>
          {res.narrative && <Text as="p" size="2" mb="3">{res.narrative}</Text>}
          {choice.why && <Text as="p" size="2" color="gray" mb="3"><em>Why this chart:</em> {choice.why}</Text>}

          <SegmentedControl.Root value={opt.id} onValueChange={setShown} size="1" mb="4">
            {choice.options.map((o) => (
              <SegmentedControl.Item key={o.id} value={o.id}>{o.id}. {o.kind.replace("_", " ")}{o.id === choice.option.id ? " ★" : ""}</SegmentedControl.Item>
            ))}
          </SegmentedControl.Root>
          <Text as="div" size="1" color="gray" mb="3">{opt.describe}</Text>

          {opt.kind !== "table" && <AnswerChart option={opt} columns={res.columns} rows={res.rows} />}

          <Table.Root mt="4" variant="surface" size="1">
            <Table.Header><Table.Row>{res.columns.map((c) => <Table.ColumnHeaderCell key={c}>{c}</Table.ColumnHeaderCell>)}</Table.Row></Table.Header>
            <Table.Body>
              {res.rows.slice(0, opt.kind === "table" ? 100 : 12).map((row, i) => (
                <Table.Row key={i}>{row.map((v, j) => <Table.Cell key={j} className="tabular">{v == null ? "—" : String(v)}</Table.Cell>)}</Table.Row>
              ))}
            </Table.Body>
          </Table.Root>

          <Text as="div" size="1" color="gray" mt="3">
            Columns as the picker read them: {choice.profile.map((p) => `${p.name} (${p.kind}${p.unit ? `, ${p.unit}` : ""})`).join(" · ")}
          </Text>
          {res.sql && <Code size="1" mt="2" style={{ display: "block", whiteSpace: "pre-wrap" }}>{res.sql}</Code>}
        </Card>
      )}
    </Box>
  );
}
