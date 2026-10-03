"use client";

import { ArrowDownIcon, ArrowRightIcon, CheckIcon, MoonIcon, SunIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Container, Flex, Grid, Heading, IconButton, Text, Theme, Tooltip } from "@radix-ui/themes";
import {
  motion,
  useInView,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from "motion/react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useRef, useState } from "react";
import { Wordmark } from "@/components/bits";
import { Marquee, Paper, SplitText, Stamp } from "@/components/ledger";
import { CountUp } from "@/components/motion";
import { BACKGROUND, SYSTEMS } from "@/components/landing/story-scene";
import { PERSONAS, useSession } from "@/lib/session";
import { useHydrated } from "@/lib/stored";

const StoryScene = dynamic(() => import("@/components/landing/story-scene"), { ssr: false });

const CHAPTERS = [
  { at: 0.12, n: "01", title: "Five systems. Five keys. One person.", body: "Cards, loans, deposits, CRM and collections each file Jane under a different customer key. None of them knows the others." },
  { at: 0.32, n: "02", title: "Kept resolves them into one golden ID.", body: "Exact links first, then probabilistic matching. Every customer becomes one point of light, with its match confidence and lineage. Hover one." },
  { at: 0.56, n: "03", title: "Meet Jane.", body: "Her pay is due in three days and is down 27% on her average. She answers calls after six. Her last promise fell due before payday, and broke." },
  { at: 0.76, n: "04", title: "A promise she can keep.", body: "Dated the day after payday, sized to her spare cash, checked against every rule, and released only when two people sign." },
];
const REASONS: [string, number][] = [
  ["Pay lands in 3 days", 9],
  ["Pay is down 27% on the 3-month average", 6],
  ["Answers 80% of calls after 18:00", 4],
];
const EVENTS = [
  ["REC", "CS-2026-118204", "call · amber · +36 pts over waiting"],
  ["REF", "“kept rate by gender”", "protected attribute · suggested: kept rate by product"],
  ["REL", "CS-2026-344961", "hardship review · red · 2 of 2 signatures"],
  ["STOP", "CS-2026-612390", "cease request · no contact"],
  ["ASK", "kept rate by product, 90d", "mortgage 55% of 1,295 promises"],
  ["CXL", "CS-2026-302680", "superseded by a fresh recommendation"],
  ["HLD", "CS-2026-700145", "hold-out · old strategy · same safety rules"],
];

/** 0 → 1 → 0 across [a, b], with soft edges: a chapter's visibility. */
function useBand(p: MotionValue<number>, a: number, b: number, edge = 0.04) {
  return useTransform(p, [a - edge, a, b - edge, b], [0, 1, 1, 0]);
}

export default function Landing() {
  const router = useRouter();
  const { me, signIn } = useSession();
  const ready = useHydrated();
  const still = useReducedMotion() ?? false;
  const { resolvedTheme, setTheme } = useTheme();
  const light = ready && resolvedTheme === "light"; // dark until we know: the scene is made for it
  const bg = light ? BACKGROUND.light : BACKGROUND.dark;

  const story = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: story, offset: ["start start", "end end"] });
  const p = useSpring(scrollYProgress, { stiffness: 140, damping: 32, mass: 0.6 });
  const { scrollYProgress: page, scrollY } = useScroll(); // whole page: the reading-progress line
  const barOpacity = useTransform(scrollY, [20, 120], [0, 1]);

  const heroOpacity = useTransform(p, [0, 0.09], [1, 0]);
  const l1 = useTransform(p, [0, 0.1], [0, -140]);
  const l2 = useTransform(p, [0, 0.1], [0, 90]);
  const l3 = useTransform(p, [0, 0.1], [0, -60]);
  const cardOpacity = useTransform(p, [0.7, 0.76], [0, 1]);
  const cardY = useTransform(p, [0.7, 0.78], [60, 0]);
  const legendOpacity = useBand(p, 0.1, 0.34);
  const spotlight = useTransform(p, [0.55, 0.72], [0, 1]); // focus on Jane: wash out the rest

  const enter = () => router.push(ready && me ? me.home : "/signin");
  const demo = () => {
    if (!me) signIn(PERSONAS[0]);
    router.push("/demo");
  };
  const jump = (to: number) => {
    const el = story.current;
    if (!el) return;
    const top = el.offsetTop + to * (el.offsetHeight - window.innerHeight);
    window.scrollTo({ top, behavior: still ? "auto" : "smooth" });
  };

  return (
    <Theme appearance={light ? "light" : "dark"} accentColor="ruby" grayColor="sand" radius="medium" hasBackground={false}>
      <Box style={{ background: bg, color: "var(--gray-12)", transition: "background 300ms" }}>
        <motion.div
          aria-hidden
          style={{ position: "fixed", top: 0, left: 0, right: 0, height: 2, zIndex: 40, transformOrigin: "0 50%", scaleX: page,
            background: "linear-gradient(to right, #c8102e, #e54666, #ffcf87)" }}
        />
        {/* ------------------------------------------------ top bar */}
        <Box position="fixed" top="0" left="0" right="0" style={{ zIndex: 30 }}>
          {/* frosted bar fades in once the page moves, so nothing scrolls under bare buttons */}
          <motion.div
            aria-hidden
            className="glass"
            style={{ position: "absolute", inset: 0, opacity: barOpacity, background: `${bg}c7`, borderBottom: "1px solid var(--gray-a4)" }}
          />
          <Grid columns="1fr auto 1fr" align="center" gap="4" px={{ initial: "4", md: "6" }} style={{ height: 64, position: "relative" }}>
            <Flex align="center" gap="3">
              <Wordmark />
              <Box display={{ initial: "none", md: "block" }}>
                <Text size="1" style={{ color: "var(--gray-10)", letterSpacing: "0.02em" }}>Promises customers can keep</Text>
              </Box>
            </Flex>
            <Flex gap="1" align="center" display={{ initial: "none", md: "flex" }} asChild>
              <nav aria-label="Sections">
                <Button size="2" variant="ghost" color="gray" onClick={() => jump(0.2)}>The story</Button>
                <Button size="2" variant="ghost" color="gray" onClick={() => document.getElementById("numbers")?.scrollIntoView({ behavior: still ? "auto" : "smooth" })}>The numbers</Button>
                <Button size="2" variant="ghost" color="gray" onClick={() => document.getElementById("safety")?.scrollIntoView({ behavior: still ? "auto" : "smooth" })}>Safety</Button>
                <Button size="2" variant="ghost" color="gray" onClick={demo}>Guided demo</Button>
              </nav>
            </Flex>
            <Flex gap="3" align="center" justify="end">
              <Tooltip content={light ? "Dark mode" : "Light mode"}>
                <IconButton size="2" variant="ghost" color="gray" aria-label="Toggle colour mode" onClick={() => setTheme(light ? "dark" : "light")}>
                  {light ? <MoonIcon /> : <SunIcon />}
                </IconButton>
              </Tooltip>
              <Button size="2" variant="solid" radius="full" onClick={enter}>
                {ready && me ? `Continue as ${me.name.split(" ")[0]}` : "Sign in"} <ArrowRightIcon />
              </Button>
            </Flex>
          </Grid>
        </Box>

        {/* ------------------------------------------------ the story: one pinned scene, driven by scroll */}
        <Box ref={story} style={{ height: "520vh", position: "relative" }}>
          <Box position="sticky" top="0" style={{ height: "100vh", overflow: "hidden" }}>
            <StoryScene key={light ? "light" : "dark"} progress={p} still={still} light={light} />
            <motion.div
              aria-hidden
              style={{
                opacity: spotlight, position: "absolute", inset: 0, pointerEvents: "none",
                background: `radial-gradient(ellipse 34% 42% at 50% 50%, transparent 0%, transparent 45%, ${bg}d9 78%, ${bg} 100%)`,
              }}
            />

            {/* hero */}
            <motion.div style={{ opacity: heroOpacity, position: "absolute", inset: 0, pointerEvents: "none" }}>
              <Flex direction="column" justify="center" px="5" style={{ height: "100%", maxWidth: 1320, margin: "0 auto" }}>
                <Badge size="2" radius="full" variant="surface" style={{ width: "fit-content" }}>
                  CIBC Collections Hackathon · Team Sharpe Shooters
                </Badge>
                <Heading as="h1" mt="5" style={{ fontSize: "clamp(48px, 9vw, 128px)", lineHeight: 0.92, letterSpacing: "-0.035em" }}>
                  <motion.span style={{ display: "block", x: l1 }}><SplitText text="Promises" delay={0.3} /></motion.span>
                  <motion.span style={{ display: "block", x: l2 }}><SplitText text="customers" delay={0.45} /></motion.span>
                  <motion.span style={{ display: "block", x: l3, color: "var(--accent-10)" }}>
                    <SplitText text="can keep." delay={0.6} />
                  </motion.span>
                </Heading>
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.2, duration: 0.8 }} style={{ pointerEvents: "auto" }}>
                  <Text as="p" size="5" mt="5" style={{ maxWidth: 560, color: "var(--gray-11)" }}>
                    Collections that start from the customer: one view of them, one guarded action, dated after payday and
                    released by a person.
                  </Text>
                  <Flex gap="3" mt="6" wrap="wrap">
                    <Button size="4" onClick={demo}>Run the guided demo <ArrowRightIcon /></Button>
                    <Button size="4" variant="surface" color="gray" onClick={() => jump(0.2)}>Scroll the story <ArrowDownIcon /></Button>
                  </Flex>
                </motion.div>
              </Flex>
            </motion.div>

            {/* system legend while records are scattered */}
            <motion.div style={{ opacity: legendOpacity, position: "absolute", left: 0, right: 0, bottom: 28, pointerEvents: "none" }}>
              <Flex justify="center" gap="4" wrap="wrap">
                {SYSTEMS.map((s) => (
                  <Flex key={s.name} align="center" gap="2">
                    <span style={{ width: 10, height: 10, borderRadius: 99, background: s.color, boxShadow: `0 0 10px ${s.color}` }} />
                    <Text size="2" style={{ color: "var(--gray-11)" }}>{s.name}</Text>
                  </Flex>
                ))}
              </Flex>
            </motion.div>

            {/* chapters */}
            {CHAPTERS.map((c, i) => (
              <Chapter key={c.n} p={p} from={c.at} to={CHAPTERS[i + 1]?.at ?? 1.05} chapter={c} />
            ))}

            {/* Jane's card, on paper */}
            <motion.div style={{ opacity: cardOpacity, y: cardY, position: "absolute", right: "max(20px, 6vw)", top: "50%", translateY: "-50%", width: "min(420px, calc(100vw - 40px))" }}>
              <JaneCard p={p} />
            </motion.div>

          </Box>
        </Box>

        {/* ------------------------------------------------ ticker of real case events */}
        <Box py="5" style={{ borderTop: "1px solid var(--gray-a4)", borderBottom: "1px solid var(--gray-a4)" }}>
          <Marquee
            items={EVENTS.map(([k, a, b]) => (
              <>
                <Text style={{ color: k === "REF" || k === "STOP" ? "var(--amber-10)" : "var(--accent-10)" }} weight="bold">{k}</Text>{" "}
                <Text style={{ color: "var(--gray-12)" }}>{a}</Text> <Text style={{ color: "var(--gray-10)" }}>{b}</Text>
              </>
            ))}
          />
        </Box>

        {/* ------------------------------------------------ the ledger: numbers as entries */}
        <Container id="numbers" size="3" px="5" py="9" style={{ scrollMarginTop: 72 }}>
          <Heading size="9" className="serif" style={{ lineHeight: 1 }}>
            <SplitText text="The books, as we found them." />
          </Heading>
          <Ledger />
        </Container>

        {/* ------------------------------------------------ safe by construction, as a receipt */}
        <Container id="safety" size="4" px="5" pb="9" style={{ scrollMarginTop: 72 }}>
          <Grid columns={{ initial: "1", md: "1fr 380px" }} gap="8" align="center">
            <Box>
              <Text size="2" weight="bold" style={{ color: "var(--accent-10)", letterSpacing: "0.12em" }}>SAFE BY CONSTRUCTION</Text>
              <Heading size="8" mt="3" style={{ lineHeight: 1.05 }}>
                <SplitText text="Rules run before the model and again at release. The model never sends anything." stagger={0.03} />
              </Heading>
              <Text as="p" size="4" mt="4" style={{ color: "var(--gray-11)", maxWidth: 560 }}>
                Every card is a proposal. A hardship flag sends it to a specialist and a second person; a cease request or a
                payment cancels it; an approval expires in four hours.
              </Text>
            </Box>
            <Receipt />
          </Grid>
        </Container>

        {/* ------------------------------------------------ the promise note */}
        <Container size="3" px="5" pb="9">
          <PromiseNote onDemo={demo} onEnter={enter} />
          <Text as="p" size="1" align="center" mt="7" style={{ color: "var(--gray-10)" }}>
            Fully synthetic data · no protected attributes in any decision · free, local and open models only
          </Text>
        </Container>
      </Box>
    </Theme>
  );
}

function Chapter({ p, from, to, chapter }: { p: MotionValue<number>; from: number; to: number; chapter: (typeof CHAPTERS)[number] }) {
  const opacity = useBand(p, from, to);
  const y = useTransform(p, [from - 0.04, from, to - 0.04, to], [40, 0, 0, -40]);
  return (
    <motion.div style={{ opacity, y, position: "absolute", left: "max(20px, 6vw)", bottom: "14vh", maxWidth: 520, pointerEvents: "none" }}>
      <Text className="serif" style={{ fontSize: 72, lineHeight: 1, color: "var(--accent-a8)" }}>{chapter.n}</Text>
      <Heading size="8" mt="2" style={{ lineHeight: 1.05 }}>{chapter.title}</Heading>
      <Text as="p" size="4" mt="3" style={{ color: "var(--gray-11)" }}>{chapter.body}</Text>
    </motion.div>
  );
}

/** Jane's card writes itself as the scroll moves: reasons tick in, then two signatures, then the stamp. */
function JaneCard({ p }: { p: MotionValue<number> }) {
  const [stage, setStage] = useState(0);
  useMotionValueEvent(p, "change", (v) => {
    const s = v < 0.78 ? 0 : v < 0.81 ? 1 : v < 0.84 ? 2 : v < 0.87 ? 3 : v < 0.91 ? 4 : v < 0.95 ? 5 : 6;
    if (s !== stage) setStage(s);
  });
  return (
    <Paper>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.1em", color: "#78716c" }}>CASE CS-2026-118204 · G-910001</div>
      <div className="serif" style={{ fontSize: 26, fontWeight: 700, lineHeight: "32px", marginTop: 4 }}>Call, Tue 18:00–20:00</div>
      <div style={{ fontSize: 14, color: "#57534e" }}>$140 a month × 3 · due the day after payday · fits ~$160 spare cash</div>
      <div style={{ marginTop: 8 }}>
        {REASONS.map(([r, pts], i) => (
          <motion.div key={r} initial={false} animate={{ opacity: stage > i ? 1 : 0.15, x: stage > i ? 0 : -8 }} transition={{ type: "spring", stiffness: 300, damping: 26 }}
            style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><CheckIcon aria-hidden /> {r}</span>
            <span style={{ fontFamily: "var(--font-mono)", color: "#a8a29e" }}>+{pts}.0</span>
          </motion.div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 10 }}>
        {[["Maya Singh", "hardship specialist", 4], ["Tom Leblanc", "team lead", 5]].map(([name, role, at]) => (
          <div key={String(name)} style={{ borderTop: "1px solid #a8a29e", paddingTop: 2 }}>
            <motion.div className="hand" initial={false} animate={{ clipPath: stage >= Number(at) ? "inset(0 0% 0 0)" : "inset(0 100% 0 0)" }} transition={{ duration: 0.7, ease: "easeOut" }}>
              {name}
            </motion.div>
            <div style={{ fontSize: 10, color: "#78716c", letterSpacing: "0.08em", lineHeight: "14px" }}>{String(role).toUpperCase()}</div>
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", right: 22, bottom: 64 }}>
        <Stamp text="Released" sub="2 of 2 · rechecked" ink="grass" rotate={-11} play={stage >= 6} />
      </div>
    </Paper>
  );
}

function Ledger() {
  const rows: [string, number, (n: number) => string][] = [
    ["Customers", 1_000_000, (n) => Math.round(n).toLocaleString("en-CA")],
    ["CRM records (some people twice)", 1_020_000, (n) => Math.round(n).toLocaleString("en-CA")],
    ["Accounts across products", 1_840_000, (n) => Math.round(n).toLocaleString("en-CA")],
    ["Collections cases", 340_000, (n) => Math.round(n).toLocaleString("en-CA")],
    ["Contact attempts", 2_500_000, (n) => Math.round(n).toLocaleString("en-CA")],
    ["Agent notes", 1_500_000, (n) => Math.round(n).toLocaleString("en-CA")],
    ["Source tables", 31, (n) => Math.round(n).toString()],
  ];
  return (
    <Box mt="7" style={{ fontFamily: "var(--font-mono)", fontSize: 15 }}>
      {rows.map(([label, v, f], i) => (
        <motion.div key={label} initial={{ opacity: 0, x: -16 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: "-40px" }}
          transition={{ type: "spring", stiffness: 260, damping: 28, delay: i * 0.05 }}
          style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--gray-a4)" }}>
          <span style={{ color: "var(--gray-11)" }}>{label}</span>
          <span style={{ flex: 1, borderBottom: "1px dotted var(--gray-a6)", transform: "translateY(-4px)" }} />
          <span className="tabular" style={{ color: "var(--gray-12)", fontWeight: 600 }}><CountUp value={v} format={f} /></span>
        </motion.div>
      ))}
      <motion.div initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: 0.5 }}
        style={{ display: "flex", justifyContent: "space-between", padding: "14px 0", borderBottom: "3px double var(--gray-a8)", fontSize: 18 }}>
        <span style={{ fontWeight: 700 }}>Views of each customer</span>
        <span style={{ fontWeight: 700, color: "var(--accent-10)", display: "inline-flex", alignItems: "center", gap: 8 }}>
          5 <ArrowRightIcon width={18} height={18} aria-label="becomes" /> 1
        </span>
      </motion.div>
    </Box>
  );
}

function Receipt() {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "-80px" });
  const lines = ["Hard stops", "Consent per channel", "Customer-local calling hours", "Weekly contact cap", "Hardship override", "Uplift over doing nothing", "Kept sizing to spare cash", "Two-person release"];
  return (
    <motion.div ref={ref} initial={{ y: -40, opacity: 0 }} animate={seen ? { y: 0, opacity: 1 } : undefined} transition={{ type: "spring", stiffness: 120, damping: 18 }}
      style={{ background: "#f4efe6", color: "#1c1917", padding: "22px 22px 30px", fontFamily: "var(--font-mono)", fontSize: 13, position: "relative",
        clipPath: "polygon(0 0, 100% 0, 100% calc(100% - 8px), 95% 100%, 90% calc(100% - 8px), 85% 100%, 80% calc(100% - 8px), 75% 100%, 70% calc(100% - 8px), 65% 100%, 60% calc(100% - 8px), 55% 100%, 50% calc(100% - 8px), 45% 100%, 40% calc(100% - 8px), 35% 100%, 30% calc(100% - 8px), 25% 100%, 20% calc(100% - 8px), 15% 100%, 10% calc(100% - 8px), 5% 100%, 0 calc(100% - 8px))" }}>
      <div style={{ textAlign: "center", fontWeight: 700, letterSpacing: "0.2em" }}>KEPT · RELEASE GATE</div>
      <div style={{ textAlign: "center", fontSize: 11, color: "#78716c" }}>CS-2026-118204 · 14:02:17 ET</div>
      <div style={{ borderTop: "1px dashed #a8a29e", margin: "12px 0" }} />
      {lines.map((l, i) => (
        <motion.div key={l} initial={{ opacity: 0 }} animate={seen ? { opacity: 1 } : undefined} transition={{ delay: 0.4 + i * 0.14 }}
          style={{ display: "flex", justifyContent: "space-between", lineHeight: "24px" }}>
          <span>{l}</span>
          <span style={{ color: "#15803d", fontWeight: 700 }}>PASS</span>
        </motion.div>
      ))}
      <div style={{ borderTop: "1px dashed #a8a29e", margin: "12px 0" }} />
      <motion.div initial={{ opacity: 0 }} animate={seen ? { opacity: 1 } : undefined} transition={{ delay: 1.6 }}
        style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 15 }}>
        <span>RELEASED</span>
        <span>2/2</span>
      </motion.div>
      <div style={{ position: "absolute", right: 18, top: 70 }}>
        <Stamp text="Checked" ink="red" rotate={12} size={0.8} play={seen} />
      </div>
    </motion.div>
  );
}

function PromiseNote({ onDemo, onEnter }: { onDemo: () => void; onEnter: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "-120px" });
  return (
    <div ref={ref}>
      <motion.div initial={{ rotate: -2, y: 40, opacity: 0 }} whileInView={{ rotate: -1, y: 0, opacity: 1 }} viewport={{ once: true }} transition={{ type: "spring", stiffness: 140, damping: 18 }}>
        <Paper style={{ padding: "40px 40px 40px 80px", fontSize: 20 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.14em", color: "#78716c" }}>PROMISE TO PAY · NO. 00418</div>
          <div className="serif" style={{ fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 700, lineHeight: 1.15, marginTop: 10 }}>
            I promise to pay <u style={{ textDecorationColor: "#c8102e" }}>$140</u> on <u style={{ textDecorationColor: "#c8102e" }}>Saturday, October 3</u>,
            the day after my payday.
          </div>
          <div style={{ display: "flex", alignItems: "end", justifyContent: "space-between", marginTop: 28, gap: 20, flexWrap: "wrap" }}>
            <div style={{ borderTop: "1px solid #a8a29e", minWidth: 220 }}>
              <motion.div className="hand" style={{ fontSize: 34 }} initial={{ clipPath: "inset(0 100% 0 0)" }} animate={seen ? { clipPath: "inset(0 0% 0 0)" } : undefined} transition={{ duration: 1.1, delay: 0.5 }}>
                Jane Doe
              </motion.div>
              <div style={{ fontSize: 11, color: "#78716c", letterSpacing: "0.1em" }}>A PROMISE SHE CAN KEEP</div>
            </div>
            <Stamp text="Kept" sub="paid oct 3" ink="grass" rotate={-14} size={1.4} play={seen} />
          </div>
        </Paper>
      </motion.div>
      <Flex gap="3" justify="center" mt="7" wrap="wrap">
        <Button size="4" onClick={onDemo}>Run the guided demo <ArrowRightIcon /></Button>
        <Button size="4" variant="surface" color="gray" onClick={onEnter}>Open the workspace</Button>
      </Flex>
    </div>
  );
}
