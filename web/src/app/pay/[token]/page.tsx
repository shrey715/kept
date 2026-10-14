"use client";

// What the customer's SMS opens (#89). Every option is a plan Kept already sized: due 1-2 days after payday,
// each instalment within the customer's spare cash. The customer picks one; there's no free date, because a
// date before payday is the promise that breaks. No sign-in and no name, account or case ID on the page.
// When the bank doesn't know their payday or spare cash, the page asks (next payday, how often, what they can
// put toward it each payday) and the server sizes the plans from those answers, never from a client amount.
import { CheckCircledIcon, CheckIcon, LockClosedIcon } from "@radix-ui/react-icons";
import { Box, Callout, Card, Flex, Link, RadioCards, Select, Text, TextField } from "@radix-ui/themes";
import { use, useEffect, useState } from "react";
import { MapleMark } from "@/components/bits";
import { api, type PayOffer, type PromiseSizing, type StatedPay } from "@/lib/api";

const money = (v: string | number) => new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(Number(v));
const day = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString("en-CA", { weekday: "short", day: "numeric", month: "short" });

const iso = (d: Date) => d.toLocaleDateString("en-CA"); // YYYY-MM-DD in the customer's own time zone
const FREQUENCIES: [StatedPay["frequency"], string][] = [
  ["weekly", "Every week"],
  ["biweekly", "Every two weeks"],
  ["semi_monthly", "Twice a month"],
  ["monthly", "Once a month"],
];

function describe(o: PromiseSizing): string {
  if (o.installments === 1) return `${money(o.amount)} on ${day(o.due_date)}, the day after your pay`;
  return `${o.installments} × ${money(o.amount)}, starting ${day(o.due_date)}, one each payday`;
}

export default function PayPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [offer, setOffer] = useState<PayOffer | null>(null);
  const [pick, setPick] = useState<string>("");
  const [done, setDone] = useState<PromiseSizing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stated, setStated] = useState<StatedPay | null>(null);
  const [payday, setPayday] = useState("");
  const [frequency, setFrequency] = useState<StatedPay["frequency"]>("biweekly");
  const [perPayday, setPerPayday] = useState("");

  useEffect(() => {
    api.payOffer(token).then(show, (e: Error) => setError(e.message));
  }, [token]);

  function show(o: PayOffer) {
    setOffer(o);
    setPick(String(o.options[0]?.installments ?? ""));
  }

  async function askPlans() {
    const answers: StatedPay = { next_payday: payday, frequency, per_payday: perPayday };
    setBusy(true);
    setError(null);
    try {
      show(await api.payPlans(token, answers));
      setStated(answers);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    try {
      setDone(await api.payChoose(token, Number(pick), stated));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box className="k-pay">
      <Flex align="center" gap="2" mb="4">
        <span className="k-chip" style={{ width: 36, height: 36 }}>
          <MapleMark />
        </span>
        <Text weight="bold">Maple Bank</Text>
        <span className="k-badge" style={{ marginLeft: "auto", gap: 6, height: 28, borderRadius: 999, padding: "0 10px" }}>
          <LockClosedIcon /> Secure link
        </span>
      </Flex>
      <ol className="k-pay-steps" aria-label="Steps">
        {["Your pay", "Pick a plan", "Done"].map((label, i) => {
          const at = done ? 2 : offer && !offer.ask ? 1 : 0;
          return (
            <li key={label} data-state={i < at ? "done" : i === at ? "now" : "next"}>
              <span>{i < at ? <CheckIcon /> : i + 1}</span>
              {label}
            </li>
          );
        })}
      </ol>
      {error && (
        <div className="k-card t-rose" style={{ textAlign: "center", padding: 28 }}>
          <span className="k-chip round" style={{ width: 48, height: 48, margin: "0 auto 12px" }}>
            <LockClosedIcon />
          </span>
          <Text as="div" size="4" weight="medium">
            {error.charAt(0).toUpperCase() + error.slice(1)}
          </Text>
          <Text as="p" size="2" color="gray" mt="1">
            Links work once the bank has sent them, and for a few days after. Call us and we&apos;ll send a new one.
          </Text>
        </div>
      )}
      {done && (
        <Card size="3">
          <Flex direction="column" align="center" gap="3" style={{ textAlign: "center" }}>
            <CheckCircledIcon width={32} height={32} color="var(--grass-9)" />
            <h1 className="k-display" style={{ fontSize: 30 }}>You&apos;re all set</h1>
            <Text>{describe(done)}</Text>
            <Text size="2" color="gray">The first payment is on {day(done.due_date)}. We&apos;ll remind you the day before each one.</Text>
          </Flex>
        </Card>
      )}
      {offer?.ask && !done && (
        <>
          <h1 className="k-display" style={{ fontSize: 30, marginBottom: 6 }}>Let&apos;s build a plan around your pay</h1>
          <Text as="p" size="2" color="gray" mb="4">
            Three quick questions, so every payment lands right after you&apos;re paid. We only use your answers to set up this plan.
          </Text>
          <Flex direction="column" gap="4">
            <label>
              <Text as="div" size="2" weight="bold" mb="1">When&apos;s your next payday?</Text>
              <TextField.Root type="date" value={payday} min={iso(new Date())} max={iso(new Date(Date.now() + 35 * 864e5))} onChange={(e) => setPayday(e.target.value)} />
            </label>
            <label>
              <Text as="div" size="2" weight="bold" mb="1">How often are you paid?</Text>
              <Select.Root value={frequency} onValueChange={(v) => setFrequency(v as StatedPay["frequency"])}>
                <Select.Trigger style={{ width: "100%" }} />
                <Select.Content>
                  {FREQUENCIES.map(([v, label]) => <Select.Item key={v} value={v}>{label}</Select.Item>)}
                </Select.Content>
              </Select.Root>
            </label>
            <label>
              <Text as="div" size="2" weight="bold" mb="1">How much could you put toward this each payday, after rent and essentials?</Text>
              <TextField.Root type="number" inputMode="decimal" min="1" step="0.01" placeholder="0.00" value={perPayday} onChange={(e) => setPerPayday(e.target.value)}>
                <TextField.Slot>$</TextField.Slot>
              </TextField.Root>
            </label>
            <button className="k-strong-btn k-pay-cta" disabled={busy || !payday || !(Number(perPayday) > 0)} onClick={() => void askPlans()}>
              {busy ? <span className="k-spin" /> : "Show my options"}
            </button>
          </Flex>
        </>
      )}
      {offer && !offer.ask && !done && (
        <>
          <h1 className="k-display" style={{ fontSize: 30, marginBottom: 6 }}>Pick a plan that works for you</h1>
          {offer.amount_due != null && (
            <Text as="p" size="2" color="gray" mb="4">
              {money(offer.amount_due)} is overdue. Every option below is timed for right after your payday and fits{" "}
              {stated ? `the ${money(stated.per_payday)} a payday you told us you can manage.` : "what you usually have left after bills."}
            </Text>
          )}
          {offer.options.length === 0 ? (
            <Callout.Root><Callout.Text>Let&apos;s talk instead: there isn&apos;t a plan we can set up here.</Callout.Text></Callout.Root>
          ) : (
            <>
              <RadioCards.Root value={pick} onValueChange={setPick} columns="1" gap="3">
                {offer.options.map((o) => (
                  <RadioCards.Item key={o.installments} value={String(o.installments)}>
                    <Flex direction="column" width="100%">
                      <Text weight="bold">{o.installments === 1 ? "Pay in full" : `${o.installments} payments`}</Text>
                      <Text size="2">{describe(o)}</Text>
                    </Flex>
                  </RadioCards.Item>
                ))}
              </RadioCards.Root>
              <button className="k-strong-btn k-pay-cta" style={{ marginTop: 16 }} disabled={busy || !pick} onClick={() => void confirm()}>
                {busy ? <span className="k-spin" /> : "Confirm this plan"}
              </button>
            </>
          )}
          <Text as="p" size="2" color="gray" mt="5">
            Money tight right now? <Link href="tel:18005550100">Call us about a hardship plan</Link>: we can pause or lower payments.
          </Text>
        </>
      )}
    </Box>
  );
}
