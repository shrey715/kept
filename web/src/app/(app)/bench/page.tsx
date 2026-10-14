"use client";

// The benchmark bench: load the organisers' questions CSV (or ours), watch every question go through the Ask,
// see which rung of the ladder answered it, score it against gold when there is gold, and export the answers
// CSV in the organisers' template. One question at a time, through POST /bench/question, which asks it exactly
// as `kept benchmark` does (team-lead view, no clarification round), so the export matches the CLI's file.
import { PageHeader } from "@/components/page-header";
import { BarChartIcon, CheckIcon, Cross2Icon, DownloadIcon, PauseIcon, PlayIcon, ReloadIcon, UploadIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Code, Flex, Grid, Spinner, Table, Text, Tooltip } from "@radix-ui/themes";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CitedText, Sources, useVerify } from "@/components/citations";
import { Rise, Stagger, spring } from "@/components/motion";
import { api, type BenchOut, type BenchSuite } from "@/lib/api";
import { download, parseCsv, toCsv } from "@/lib/csv";

type Row = Record<string, string>;
type State = { status: "queued" | "running" | "done" | "error"; out?: BenchOut; error?: string };
type Color = "amber" | "grass" | "teal" | "blue" | "violet" | "plum" | "gray";

const LANES: { id: string; label: string; sub: string; color: Color }[] = [
  { id: "refused", label: "Refused", sub: "rules or scope check, before any SQL runs", color: "amber" },
  { id: "certified", label: "Certified metric", sub: "the bank's reviewed SQL; the model only fills filters", color: "grass" },
  { id: "template", label: "SQL template", sub: "our reviewed templates, dates worked out in code", color: "teal" },
  { id: "free_sql", label: "Free SQL", sub: "3 drafts, majority result, then the SQL guard", color: "blue" },
  { id: "documents", label: "Documents", sub: "current policy and incident sections, cited", color: "violet" },
  { id: "call", label: "Call transcript", sub: "the case's latest call, redacted, summarised", color: "plum" },
  { id: "clarify", label: "Unsure", sub: "would have asked a clarifying question", color: "gray" },
];
const LANE = Object.fromEntries(LANES.map((l) => [l.id, l]));
const STAGES = ["Redact PII", "Rules", "Scope", "Route", "Answer", "SQL guard", "Grounding", "CSV row"];
const ANSWER_COLUMNS = ["question_id", "answer", "sql_or_sources", "refused"];

export default function BenchPage() {
  const [suites, setSuites] = useState<BenchSuite[]>([]);
  const [name, setName] = useState<string>("");
  const [questions, setQuestions] = useState<Row[]>([]);
  const [gold, setGold] = useState<Record<string, Row>>({});
  const [state, setState] = useState<Record<string, State>>({});
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const stop = useRef(false);
  const [verify, verifyDialog] = useVerify();

  useEffect(() => {
    api.benchSuites().then(setSuites, (e: Error) => setProblem(`Couldn't list the question sets: ${e.message}`));
  }, []);

  function load(label: string, qs: Row[], g: Row[]) {
    const bad = qs.find((q) => !q.question_id || !q.question_text);
    if (bad || !qs.length) {
      setProblem("That file isn't a questions CSV: it needs question_id and question_text columns.");
      return;
    }
    setProblem(null);
    setName(label);
    setQuestions(qs);
    setGold(Object.fromEntries(g.map((r) => [r.question_id, r])));
    setState(Object.fromEntries(qs.map((q) => [q.question_id, { status: "queued" } as State])));
    setOpen(null);
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    let qs: Row[] = [];
    let g: Row[] = [];
    const names: string[] = [];
    for (const f of Array.from(files)) {
      const rows = parseCsv(await f.text());
      const head = Object.keys(rows[0] ?? {});
      if (head.includes("gold_answer")) g = rows;
      else qs = rows;
      names.push(f.name);
    }
    if (!qs.length && g.length && questions.length) {
      setGold(Object.fromEntries(g.map((r) => [r.question_id, r]))); // gold for the set already loaded
      return;
    }
    load(names.join(" + "), qs, g);
  }

  async function run(ids: string[]) {
    stop.current = false;
    setRunning(true);
    for (const id of ids) {
      if (stop.current) break;
      const q = questions.find((x) => x.question_id === id)!;
      setState((s) => ({ ...s, [id]: { status: "running" } }));
      try {
        const out = await api.benchQuestion(q, gold[id]);
        setState((s) => ({ ...s, [id]: { status: "done", out } }));
      } catch (e) {
        setState((s) => ({ ...s, [id]: { status: "error", error: (e as Error).message } }));
      }
    }
    setRunning(false);
  }

  const done = questions.filter((q) => state[q.question_id]?.status === "done");
  const todo = questions.filter((q) => ["queued", "error"].includes(state[q.question_id]?.status ?? "queued")).map((q) => q.question_id);
  const failed = questions.filter((q) => state[q.question_id]?.status === "error").map((q) => q.question_id);
  const current = questions.find((q) => state[q.question_id]?.status === "running");
  const last = [...done].reverse()[0];
  const avgMs = done.length ? done.reduce((n, q) => n + (state[q.question_id].out?.ms ?? 0), 0) / done.length : 0;

  const score = useMemo(() => {
    const graded = done.map((q) => state[q.question_id].out!).filter((o) => o.correct !== null && o.correct !== undefined);
    const inScope = graded.filter((o) => !o.should_refuse);
    const refuse = graded.filter((o) => o.should_refuse);
    const refused = done.map((q) => state[q.question_id].out!).filter((o) => o.rung === "refused" || o.rung === "clarify");
    return {
      graded: graded.length,
      accuracy: inScope.length ? inScope.filter((o) => o.correct).length / inScope.length : null,
      nIn: inScope.length,
      recall: refuse.length ? refuse.filter((o) => o.correct).length / refuse.length : null,
      nRefuse: refuse.length,
      precision: refused.length && Object.keys(gold).length ? refused.filter((o) => o.should_refuse).length / refused.filter((o) => o.should_refuse !== null).length || null : null,
    };
  }, [done, state, gold]);

  function exportCsv() {
    const rows = questions.map((q) => state[q.question_id]?.out?.row ?? { question_id: q.question_id, answer: "", sql_or_sources: "", refused: "" });
    download(`answers_${name.replace(/\W+/g, "_").toLowerCase() || "bench"}.csv`, toCsv(rows, ANSWER_COLUMNS));
  }

  return (
    <Stagger>
      <Rise>
        <PageHeader
          icon={<BarChartIcon />}
          eyebrow="Benchmark bench"
          title="Questions in, answers CSV out."
          sub={
            <>
              Load the organisers&apos; questions (or any CSV in their format), watch each one go down the Ask&apos;s ladder, and export the
              answers in their template. Each is asked exactly as <Code>kept benchmark</Code> asks it.
            </>
          }
        />
      </Rise>

      {problem && <Callout.Root color="red" mt="4"><Callout.Text>{problem}</Callout.Text></Callout.Root>}

      <Rise>
        <Grid columns={{ initial: "1", md: "1.2fr 1fr" }} gap="4" mt="5">
          <Card size="3" className="t-ice">
            <Text size="2" weight="bold">1 · Load questions</Text>
            <Flex direction="column" gap="2" mt="3">
              {suites.map((s) => (
                <motion.button key={s.name} whileHover={{ y: -2 }} whileTap={{ scale: 0.98 }} disabled={running} onClick={() => load(s.name, s.questions, s.gold)}
                  style={{ all: "unset", cursor: running ? "default" : "pointer", borderRadius: "var(--radius-3)", padding: "10px 12px", border: `1px solid ${name === s.name ? "var(--accent-8)" : "var(--gray-a5)"}`, background: name === s.name ? "var(--accent-a2)" : "transparent" }}>
                  <Flex justify="between" align="center" gap="3">
                    <Box>
                      <Text size="2" weight="bold">{s.name}</Text>
                      <Text as="p" size="1" color="gray">{s.about}</Text>
                    </Box>
                    <Flex gap="1">
                      <Badge radius="full" variant="soft">{s.questions.length} questions</Badge>
                      {s.gold.length > 0 && <Badge radius="full" variant="soft" color="grass">{s.gold.length} with gold</Badge>}
                    </Flex>
                  </Flex>
                </motion.button>
              ))}
              <DropZone disabled={running} onFiles={(f) => void upload(f)} />
            </Flex>
          </Card>

          <Card size="3" className="t-lilac">
            <Text size="2" weight="bold">2 · Run and export</Text>
            <Text as="p" size="1" color="gray" mt="1">{name ? `${name}: ${questions.length} questions, ${Object.keys(gold).length} with gold answers` : "Nothing loaded yet."}</Text>
            <Flex gap="2" mt="3" wrap="wrap">
              {!running ? (
                <Button disabled={!todo.length} onClick={() => void run(todo)}><PlayIcon /> {done.length ? `Run the remaining ${todo.length}` : "Run all"}</Button>
              ) : (
                <Button color="gray" variant="soft" onClick={() => (stop.current = true)}><PauseIcon /> Pause after this one</Button>
              )}
              <Button variant="soft" disabled={running || !failed.length} onClick={() => void run(failed)}><ReloadIcon /> Retry {failed.length || ""} failed</Button>
              <Button variant="soft" color="gray" disabled={running || !done.length} onClick={() => setState(Object.fromEntries(questions.map((q) => [q.question_id, { status: "queued" } as State])))}>Reset</Button>
              <Button variant="surface" color="grass" disabled={!done.length} onClick={exportCsv}><DownloadIcon /> Answers CSV</Button>
            </Flex>
            <Box mt="4">
              <Progress done={done.length} total={questions.length} errors={failed.length} />
              <Flex justify="between" mt="2">
                <Text size="1" color="gray">{done.length} of {questions.length} done{failed.length ? ` · ${failed.length} failed` : ""}</Text>
                <Text size="1" color="gray">{avgMs ? `${(avgMs / 1000).toFixed(1)} s a question${running ? ` · about ${Math.ceil((todo.length * avgMs) / 60000)} min left` : ""}` : ""}</Text>
              </Flex>
            </Box>
            <Grid columns="3" gap="3" mt="4">
              <Stat label="Accuracy (in scope)" value={score.accuracy} n={score.nIn} target={0.8} />
              <Stat label="Refusal recall" value={score.recall} n={score.nRefuse} target={0.95} />
              <Stat label="Answered" value={done.length ? done.filter((q) => !["refused", "clarify"].includes(state[q.question_id].out!.rung)).length / done.length : null} n={done.length} />
            </Grid>
          </Card>
        </Grid>
      </Rise>

      {questions.length > 0 && (
        <LayoutGroup>
          <Rise>
            <Card size="3" mt="4">
              <Flex justify="between" align="center" mb="3" wrap="wrap" gap="2">
                <Text size="2" weight="bold">3 · Down the ladder</Text>
                <Text size="1" color="gray">Every question passes the same checks; the lane is the step that answered it.</Text>
              </Flex>
              <Pipeline active={!!current} />
              <Box mt="3" style={{ minHeight: 52 }}>
                <AnimatePresence mode="popLayout">
                  {current ? (
                    <motion.div key={current.question_id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                      <Flex align="center" gap="3">
                        <motion.div layoutId={`q-${current.question_id}`} transition={spring}><Chip id={current.question_id} color="gray" running /></motion.div>
                        <Text size="3" className="serif">{current.question_text}</Text>
                      </Flex>
                    </motion.div>
                  ) : last ? (
                    <motion.div key="last" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                      <Text size="2" color="gray">Last: <Text weight="bold">{last.question_id}</Text> went to <Text weight="bold">{LANE[state[last.question_id].out!.rung]?.label}</Text> in {(state[last.question_id].out!.ms / 1000).toFixed(1)} s.</Text>
                    </motion.div>
                  ) : (
                    <Text size="2" color="gray">Press Run: each question appears here, then drops into the lane that answered it.</Text>
                  )}
                </AnimatePresence>
              </Box>
              <Grid columns={{ initial: "2", sm: "4", lg: "7" }} gap="2" mt="3">
                {LANES.map((l) => {
                  const here = done.filter((q) => state[q.question_id].out!.rung === l.id);
                  return (
                    <Box key={l.id} p="2" style={{ borderRadius: "var(--radius-3)", background: `var(--${l.color}-a2)`, border: `1px solid var(--${l.color}-a5)`, minHeight: 120 }}>
                      <Flex justify="between" align="baseline">
                        <Text size="1" weight="bold" style={{ color: `var(--${l.color}-11)` }}>{l.label}</Text>
                        <Text size="4" weight="bold" className="tabular" style={{ color: `var(--${l.color}-11)` }}>{here.length}</Text>
                      </Flex>
                      <Text as="p" size="1" color="gray" style={{ lineHeight: 1.3 }}>{l.sub}</Text>
                      <Flex gap="1" wrap="wrap" mt="2">
                        {here.map((q) => {
                          const o = state[q.question_id].out!;
                          return (
                            <motion.div key={q.question_id} layoutId={`q-${q.question_id}`} transition={spring} onClick={() => setOpen(q.question_id)} style={{ cursor: "pointer" }}>
                              <Chip id={q.question_id} color={o.correct === true ? "grass" : o.correct === false ? "red" : l.color} mark={o.correct} />
                            </motion.div>
                          );
                        })}
                      </Flex>
                    </Box>
                  );
                })}
              </Grid>
            </Card>
          </Rise>
        </LayoutGroup>
      )}

      {questions.length > 0 && (
        <Rise>
          <Card size="3" mt="4">
            <Text size="2" weight="bold">4 · Every question</Text>
            <Text as="p" size="1" color="gray" mb="3">Click a row for the answer, its sources and the exact CSV row that will be exported.</Text>
            <Table.Root size="1" variant="ghost">
              <Table.Header>
                <Table.Row>
                  <Table.ColumnHeaderCell>ID</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>Question</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>Lane</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>Result</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell justify="end">Time</Table.ColumnHeaderCell>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {questions.map((q) => {
                  const st = state[q.question_id] ?? { status: "queued" };
                  const o = st.out;
                  const lane = o ? LANE[o.rung] : undefined;
                  const isOpen = open === q.question_id;
                  return [
                    <Table.Row key={q.question_id} onClick={() => setOpen(isOpen ? null : q.question_id)} style={{ cursor: "pointer", background: isOpen ? "var(--accent-a2)" : undefined }}>
                      <Table.Cell><Text weight="bold" className="tabular">{q.question_id}</Text>{q.split && <Badge ml="2" size="1" variant="outline" color="gray">{q.split}</Badge>}</Table.Cell>
                      <Table.Cell style={{ maxWidth: 520 }}><Text size="2">{q.question_text}</Text></Table.Cell>
                      <Table.Cell>
                        {st.status === "running" ? <Spinner /> : st.status === "error" ? <Badge color="red">error</Badge> : lane ? <Badge color={lane.color} variant="soft">{lane.label}</Badge> : <Text size="1" color="gray">queued</Text>}
                      </Table.Cell>
                      <Table.Cell>
                        {o?.correct === true && <Badge color="grass"><CheckIcon /> {o.should_refuse ? "refused, as it should" : "matches gold"}</Badge>}
                        {o?.correct === false && <Badge color="red"><Cross2Icon /> {o.should_refuse ? "should have refused" : "differs from gold"}</Badge>}
                        {o && o.correct == null && <Text size="1" color="gray">{o.row.refused === true || o.row.refused === "true" ? "refused" : "answered"} · no gold</Text>}
                      </Table.Cell>
                      <Table.Cell justify="end"><Text size="1" color="gray" className="tabular">{o ? `${(o.ms / 1000).toFixed(1)} s` : ""}</Text></Table.Cell>
                    </Table.Row>,
                    isOpen && (
                      <Table.Row key={`${q.question_id}-open`}>
                        <Table.Cell colSpan={5}>
                          <Detail q={q} st={st} gold={gold[q.question_id]} onVerify={verify} onRetry={() => void run([q.question_id])} running={running} />
                        </Table.Cell>
                      </Table.Row>
                    ),
                  ];
                })}
              </Table.Body>
            </Table.Root>
          </Card>
        </Rise>
      )}
      {verifyDialog}
    </Stagger>
  );
}

function DropZone({ onFiles, disabled }: { onFiles: (f: FileList | null) => void; disabled?: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <Box
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) onFiles(e.dataTransfer.files); }}
      onClick={() => !disabled && input.current?.click()}
      style={{ cursor: disabled ? "default" : "pointer", borderRadius: "var(--radius-3)", padding: 16, textAlign: "center", border: `1.5px dashed ${over ? "var(--accent-9)" : "var(--gray-a6)"}`, background: over ? "var(--accent-a3)" : "var(--gray-a2)", transition: "all 150ms" }}
    >
      <UploadIcon />
      <Text as="p" size="2" weight="medium" mt="1">Drop a questions CSV here, or click to choose</Text>
      <Text as="p" size="1" color="gray">Add a gold CSV (benchmark_dev_answers format) with it to score the run. Both files at once is fine.</Text>
      <input ref={input} type="file" accept=".csv,text/csv" multiple hidden onChange={(e) => onFiles(e.target.files)} />
    </Box>
  );
}

function Pipeline({ active }: { active: boolean }) {
  return (
    <Flex gap="1" align="center" wrap="wrap">
      {STAGES.map((s, i) => (
        <Flex key={s} align="center" gap="1">
          <motion.div
            animate={active ? { backgroundColor: ["var(--gray-a3)", "var(--accent-a5)", "var(--gray-a3)"] } : { backgroundColor: "var(--gray-a3)" }}
            transition={active ? { repeat: Infinity, duration: 1.6, delay: i * 0.2 } : {}}
            style={{ borderRadius: 999, padding: "3px 10px" }}
          >
            <Text size="1" weight="medium">{s}</Text>
          </motion.div>
          {i < STAGES.length - 1 && <Text size="1" color="gray">→</Text>}
        </Flex>
      ))}
    </Flex>
  );
}

function Chip({ id, color, running, mark }: { id: string; color: string; running?: boolean; mark?: boolean | null }) {
  return (
    <Tooltip content={id}>
      <Flex align="center" gap="1" style={{ borderRadius: 999, padding: "2px 8px", fontSize: 11, fontWeight: 600, background: `var(--${color}-a4)`, color: `var(--${color}-11)`, whiteSpace: "nowrap" }}>
        {running && <Spinner size="1" />}
        {id.replace(/^[A-Z]+-/, "")}
        {mark === true && <CheckIcon width={11} height={11} />}
        {mark === false && <Cross2Icon width={11} height={11} />}
      </Flex>
    </Tooltip>
  );
}

function Progress({ done, total, errors }: { done: number; total: number; errors: number }) {
  return (
    <Box style={{ height: 8, borderRadius: 999, background: "var(--gray-a3)", overflow: "hidden", display: "flex" }}>
      <motion.div animate={{ width: `${total ? (100 * done) / total : 0}%` }} transition={spring} style={{ background: "var(--accent-9)" }} />
      <motion.div animate={{ width: `${total ? (100 * errors) / total : 0}%` }} transition={spring} style={{ background: "var(--red-9)" }} />
    </Box>
  );
}

function Stat({ label, value, n, target }: { label: string; value: number | null; n: number; target?: number }) {
  const ok = value !== null && target !== undefined ? value >= target : undefined;
  return (
    <Box>
      <Text size="1" color="gray">{label}</Text>
      <Text as="p" size="6" weight="bold" className="tabular" color={ok === undefined ? undefined : ok ? "grass" : "red"}>{value === null ? "—" : `${Math.round(100 * value)}%`}</Text>
      <Text size="1" color="gray">{n ? `of ${n}` : "no gold yet"}{target !== undefined ? ` · target ${Math.round(target * 100)}%` : ""}</Text>
    </Box>
  );
}

function Detail({ q, st, gold, onVerify, onRetry, running }: { q: Row; st: State; gold?: Row; onVerify: Parameters<typeof Sources>[0]["onOpen"]; onRetry: () => void; running: boolean }) {
  const o = st.out;
  const r = o?.response;
  return (
    <Box p="2">
      {st.status === "error" && <Callout.Root color="red" mb="3"><Callout.Text>{st.error}</Callout.Text></Callout.Root>}
      {r?.kind === "answer" && (
        <>
          <CitedText text={r.narrative} citations={r.citations} onOpen={onVerify} />
          {r.columns.length > 0 && (
            <Table.Root mt="3" size="1" variant="surface">
              <Table.Header><Table.Row>{r.columns.map((c) => <Table.ColumnHeaderCell key={c}>{c}</Table.ColumnHeaderCell>)}</Table.Row></Table.Header>
              <Table.Body>{r.rows.slice(0, 12).map((row, i) => <Table.Row key={i}>{row.map((v, j) => <Table.Cell key={j} className="tabular">{v == null ? "—" : String(v)}</Table.Cell>)}</Table.Row>)}</Table.Body>
            </Table.Root>
          )}
          <Sources r={r} onOpen={onVerify} />
        </>
      )}
      {r?.kind === "refusal" && <Callout.Root color="amber"><Callout.Text><Text weight="bold">Refused.</Text> {r.message} {r.suggestion}</Callout.Text></Callout.Root>}
      {r?.kind === "clarification" && <Callout.Root color="gray"><Callout.Text>{r.question}</Callout.Text></Callout.Root>}
      <Grid columns={{ initial: "1", md: gold ? "1fr 1fr" : "1fr" }} gap="3" mt="3">
        {o && (
          <Box>
            <Text size="1" weight="bold" color="gray">EXPORTED ROW</Text>
            <Code variant="soft" size="1" style={{ display: "block", whiteSpace: "pre-wrap", padding: 10, marginTop: 4, maxHeight: 220, overflow: "auto" }}>{toCsv([o.row], ANSWER_COLUMNS)}</Code>
          </Box>
        )}
        {gold && (
          <Box>
            <Text size="1" weight="bold" color="gray">GOLD ANSWER{q.tolerance ? ` · tolerance ${q.tolerance}` : ""}</Text>
            <Code variant="soft" size="1" color="grass" style={{ display: "block", whiteSpace: "pre-wrap", padding: 10, marginTop: 4, maxHeight: 220, overflow: "auto" }}>{gold.gold_answer}{gold.gold_sources ? `\n\nsources: ${gold.gold_sources}` : ""}</Code>
            {gold.trap_notes && <Text as="p" size="1" color="gray" mt="1">Trap: {gold.trap_notes}</Text>}
          </Box>
        )}
      </Grid>
      <Flex justify="end" mt="3"><Button size="1" variant="soft" disabled={running} onClick={onRetry}><ReloadIcon /> Ask again</Button></Flex>
    </Box>
  );
}
