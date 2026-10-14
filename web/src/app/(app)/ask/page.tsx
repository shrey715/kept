"use client";

import { PageHeader, SectionTitle } from "@/components/page-header";
import {
  ArrowUpIcon,
  BarChartIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  CounterClockwiseClockIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  MixIcon,
  QuestionMarkCircledIcon,
  ReaderIcon,
} from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Flex, Grid, Skeleton, Table, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { CitedText, Sources, useVerify } from "@/components/citations";
import { Rise, Stagger, spring } from "@/components/motion";
import { api, humanize, type AskResponse, type ChartChoice } from "@/lib/api";
import { useSession } from "@/lib/session";

// the chart bundle loads only when an answer has a chart to draw
const AnswerChart = dynamic(() => import("@/components/answer-chart").then((m) => m.AnswerChart), {
  ssr: false,
  loading: () => <Skeleton height="280px" />,
});

// released benchmark questions the Ask gets right on the dev split, one per path (metric, policy, comparison, guardrail)
const EXAMPLES: { q: string; path: string; icon: React.ReactNode }[] = [
  { q: "What is the average days past due of open cases by queue?", path: "Certified metric", icon: <BarChartIcon /> },
  { q: "How many collections cases are open today, by current bucket?", path: "Certified metric", icon: <BarChartIcon /> },
  {
    q: "Among randomised cases, compare the promise-kept rate of the champion strategy with challenger_A and challenger_B.",
    path: "Comparison",
    icon: <MixIcon />,
  },
  { q: "How many call attempts can we make on a mid-stage account in a week?", path: "Policy, quoted", icon: <ReaderIcon /> },
  { q: "List the gender and marital status of customers who broke a promise last month.", path: "Guardrail", icon: <LockClosedIcon /> },
];

const LADDER = [
  { icon: <BarChartIcon />, title: "Certified metric", body: "A reviewed SQL definition, run on the warehouse. The SQL and tables are one click away." },
  { icon: <MixIcon />, title: "Checked template", body: "Comparisons and breakdowns from templates that only touch allowed columns." },
  { icon: <ReaderIcon />, title: "Policy, quoted", body: "Rules come from the policy text itself, with the section quoted." },
  { icon: <LockClosedIcon />, title: "Refuse", body: "Protected attributes or single customers: refused, with a safe question to ask instead." },
];

const STEPS = ["Reading the question", "Choosing a grounded path", "Running it on the warehouse", "Checking every number has a source"];

export default function AskPage() {
  const { me } = useSession();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ q: string; r: AskResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chart, setChart] = useState<ChartChoice | null>(null);
  const [view, setView] = useState<"chart" | "table">("table");
  const [history, setHistory] = useState<string[]>([]);
  const [verify, verifyDialog] = useVerify();

  async function ask(question: string) {
    if (!me || !question.trim()) return;
    setQ(question);
    setBusy(true);
    setError(null);
    setChart(null);
    setView("table");
    setHistory((h) => [question, ...h.filter((x) => x !== question)].slice(0, 6));
    try {
      const r = await api.ask(question, me);
      setRes({ q: question, r });
      if (r.kind === "answer" && r.rows.length > 0) {
        // the chart is extra: if picking one fails, the answer and its table still stand
        api.chart({ question: r.question, sql: r.sql ?? null, columns: r.columns, rows: r.rows }, me).then(
          (c) => {
            if (c.option.kind === "table") return;
            setChart(c);
            setView("chart");
          },
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
        <PageHeader
          icon={<ChatBubbleIcon />}
          eyebrow="Collections Ask"
          title="Ask in plain English. See where every number comes from."
          sub="Answers are grounded: the SQL and tables behind a number, or the policy section behind a rule, one click from the original."
        />
      </Rise>

      <Grid columns={{ initial: "1", lg: "minmax(0, 1fr) 320px" }} gap="3">
        <Flex direction="column" gap="3" style={{ minWidth: 0 }}>
          <Rise>
            <form
              className="k-card"
              style={{ padding: 10, display: "flex", gap: 8, alignItems: "center", background: "var(--k-chip)", boxShadow: "0 1px 0 var(--k-line), 0 20px 50px -30px rgba(0,0,0,.35)" }}
              onSubmit={(e) => {
                e.preventDefault();
                void ask(q);
              }}
            >
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Ask about metrics, cases or policy"
                aria-label="Question"
                style={{ flex: 1, border: 0, outline: 0, background: "none", font: "400 18px/1.4 var(--default-font-family)", padding: "12px 14px", color: "var(--gray-12)" }}
              />
              <button className="k-strong-btn" style={{ width: 52, height: 52, padding: 0, justifyContent: "center" }} disabled={busy || !q.trim()} aria-label="Ask">
                {busy ? <span className="k-spin" /> : <ArrowUpIcon width={20} height={20} />}
              </button>
            </form>
          </Rise>

          {!res && !busy && !error && (
            <Grid columns={{ initial: "1", sm: "2" }} gap="3">
              {EXAMPLES.map((e, i) => (
                <Rise key={e.q}>
                  <motion.button
                    className="k-card k-link"
                    style={{ border: 0, textAlign: "left", cursor: "pointer", width: "100%", height: "100%", font: "inherit", color: "inherit" }}
                    whileHover={{ y: -3 }}
                    whileTap={{ scale: 0.98 }}
                    transition={spring}
                    onClick={() => void ask(e.q)}
                  >
                    <Flex align="center" gap="2" mb="3">
                      <span className="k-chip" style={{ width: 32, height: 32, borderRadius: 10 }}>
                        {e.icon}
                      </span>
                      <Text size="1" color="gray" weight="medium">
                        {e.path}
                      </Text>
                      <Text size="1" color="gray" ml="auto" className="tabular">
                        0{i + 1}
                      </Text>
                    </Flex>
                    <Text as="div" size="3" style={{ lineHeight: 1.4 }}>
                      {e.q}
                    </Text>
                  </motion.button>
                </Rise>
              ))}
            </Grid>
          )}

          <AnimatePresence mode="wait">
            {busy && (
              <motion.div key="thinking" className="k-card" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={spring}>
                <Thinking />
              </motion.div>
            )}
            {!busy && error && (
              <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <Callout.Root color="red">
                  <Callout.Text>Ask failed: {error}</Callout.Text>
                </Callout.Root>
              </motion.div>
            )}
            {!busy && res && r && (
              <motion.div key={res.q} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={spring}>
                {r.kind === "refusal" && (
                  <div className="k-card hi" style={{ padding: 24 }}>
                    <Flex gap="3" align="start">
                      <span className="k-chip" style={{ background: "var(--k-hi-chip)", color: "var(--k-hi-ink)" }}>
                        <ExclamationTriangleIcon />
                      </span>
                      <Box>
                        <Text as="div" size="4" weight="medium">
                          {r.message}
                        </Text>
                        <Text as="div" size="2" mt="1" style={{ opacity: 0.75 }}>
                          Refused: {humanize(r.reason)}
                        </Text>
                        {r.suggestion && (
                          <button className="k-strong-btn" style={{ marginTop: 14, height: 38, fontSize: 13 }} onClick={() => void ask(r.suggestion!.replace(/^Try:\s*/, ""))}>
                            {r.suggestion}
                          </button>
                        )}
                      </Box>
                    </Flex>
                  </div>
                )}
                {r.kind === "clarification" && (
                  <div className="k-card" style={{ padding: 24 }}>
                    <Flex gap="3" align="center">
                      <span className="k-chip">
                        <QuestionMarkCircledIcon />
                      </span>
                      <Text size="3">{r.question}</Text>
                    </Flex>
                  </div>
                )}
                {r.kind === "answer" && (
                  <div className="k-card" style={{ padding: 24 }}>
                    <Flex gap="2" wrap="wrap" mb="4" align="center">
                      <Badge size="2" color="grass" variant="soft">
                        <CheckCircledIcon /> Grounded
                      </Badge>
                      {[r.intent.kind, r.intent.metric_id, ...Object.entries(r.intent.filters ?? {}).map(([k, v]) => `${k}: ${String(v)}`), ...(r.intent.group_by ?? []).map((g) => `by ${g}`)]
                        .filter(Boolean)
                        .map((c, i) => (
                          <motion.span key={String(c)} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} transition={{ ...spring, delay: i * 0.05 }}>
                            <span className="k-badge" style={{ height: 28, padding: "0 10px", borderRadius: 999, fontWeight: 500 }}>
                              {String(c)}
                            </span>
                          </motion.span>
                        ))}
                    </Flex>
                    <Box style={{ fontSize: 17, lineHeight: 1.6 }}>
                      <CitedText text={r.narrative} citations={r.citations} onOpen={verify} />
                    </Box>
                    {r.columns.length > 0 && (
                      <Box mt="5">
                        <div className="k-tabs" role="tablist" aria-label="Answer view">
                          {chart && (
                            <button role="tab" aria-selected={view === "chart"} className="k-tab" data-active={view === "chart"} onClick={() => setView("chart")}>
                              <BarChartIcon /> Chart
                            </button>
                          )}
                          <button role="tab" aria-selected={view === "table"} className="k-tab" data-active={view === "table"} onClick={() => setView("table")}>
                            Table <span className="count">{r.rows.length}</span>
                          </button>
                        </div>
                        <AnimatePresence mode="wait">
                          {view === "chart" && chart ? (
                            <motion.div key="chart" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.2 }}>
                              <Box pt="4">
                                <AnswerChart option={chart.option} columns={r.columns} rows={r.rows} />
                                <Text as="p" size="1" color="gray" mt="1">
                                  {chart.source === "llm" ? "Chart picked by the model from the options the data supports" : "Chart picked by rules from the data's shape"}
                                </Text>
                              </Box>
                            </motion.div>
                          ) : (
                            <motion.div key="table" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.2 }}>
                              <Box pt="4" style={{ overflowX: "auto", background: "var(--k-chip)", borderRadius: 16, marginTop: 16 }}>
                                <Table.Root variant="ghost" size="1">
                                  <Table.Header>
                                    <Table.Row>
                                      {r.columns.map((c) => (
                                        <Table.ColumnHeaderCell key={c}>{c}</Table.ColumnHeaderCell>
                                      ))}
                                    </Table.Row>
                                  </Table.Header>
                                  <Table.Body>
                                    {r.rows.slice(0, 100).map((row, i) => (
                                      <Table.Row key={i}>
                                        {row.map((v, j) => (
                                          <Table.Cell key={j} className="tabular">
                                            {v == null ? "—" : String(v)}
                                          </Table.Cell>
                                        ))}
                                      </Table.Row>
                                    ))}
                                  </Table.Body>
                                </Table.Root>
                              </Box>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </Box>
                    )}
                    <Sources r={r} onOpen={verify} />
                  </div>
                )}
                {r.trace && r.trace.length > 0 && <Trace steps={r.trace} />}
                <Flex mt="3" justify="end">
                  <Button
                    variant="ghost"
                    color="gray"
                    onClick={() => {
                      setRes(null);
                      setQ("");
                    }}
                  >
                    New question
                  </Button>
                </Flex>
              </motion.div>
            )}
          </AnimatePresence>
        </Flex>

        <Flex direction="column" gap="3">
          <Rise>
            <div className="k-card">
              <SectionTitle eyebrow="Grounding" title="How an answer is grounded" mb="3" />
              <Flex direction="column" gap="3">
                {LADDER.map((s, i) => (
                  <Flex key={s.title} gap="3" align="start">
                    <span className="k-chip" style={{ width: 32, height: 32, borderRadius: 10 }}>
                      {s.icon}
                    </span>
                    <Box>
                      <Text as="div" size="2" weight="medium">
                        {i + 1}. {s.title}
                      </Text>
                      <Text as="div" size="1" color="gray">
                        {s.body}
                      </Text>
                    </Box>
                  </Flex>
                ))}
              </Flex>
            </div>
          </Rise>
          {history.length > 0 && (
            <Rise>
              <div className="k-card">
                <SectionTitle eyebrow="History" title="This session" icon={<CounterClockwiseClockIcon />} mb="2" />
                <Flex direction="column" gap="1">
                  {history.map((h) => (
                    <button key={h} className="k-link" onClick={() => void ask(h)} style={{ border: 0, background: "none", textAlign: "left", padding: "8px 10px", borderRadius: 12, cursor: "pointer", font: "inherit", color: "inherit" }}>
                      <Text size="2">{h}</Text>
                    </button>
                  ))}
                </Flex>
              </div>
            </Rise>
          )}
        </Flex>
      </Grid>
      {verifyDialog}
    </Stagger>
  );
}

/** What the Ask is doing while it works: the steps light up one after another. */
function Thinking() {
  const [n, setN] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setN((x) => Math.min(x + 1, STEPS.length - 1)), 900);
    return () => clearInterval(t);
  }, []);
  return (
    <Flex direction="column" gap="3">
      {STEPS.map((s, i) => (
        <Flex key={s} align="center" gap="3" style={{ opacity: i <= n ? 1 : 0.35, transition: "opacity 300ms" }}>
          {i < n ? <CheckCircledIcon color="var(--grass-10)" /> : i === n ? <span className="k-spin" /> : <span style={{ width: 15 }} />}
          <Text size="2">{s}</Text>
        </Flex>
      ))}
      <Skeleton height="120px" mt="2" />
    </Flex>
  );
}

/** The path the Ask actually took (kept.ask.graph): one chip per step, in order. */
function Trace({ steps }: { steps: readonly string[] }) {
  return (
    <div className="k-card" style={{ marginTop: 12, padding: "14px 18px" }}>
      <div className="k-eyebrow">How this was answered · LangGraph path</div>
      <ol className="k-trace">
        {steps.map((t, i) => {
          const [head, ...rest] = t.split(": ");
          const bad = /refused|failed|blocked|too low|disagreed|out \(/.test(t);
          return (
            <motion.li key={`${i}-${t}`} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0, transition: { delay: i * 0.06 } }} data-bad={bad}>
              <span className="k-trace-n">{i + 1}</span>
              <span>
                <b>{head}</b>
                {rest.length > 0 && <span style={{ color: "var(--gray-11)" }}> · {rest.join(": ")}</span>}
              </span>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}
