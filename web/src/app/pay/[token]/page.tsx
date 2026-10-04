"use client";

// What the customer's SMS opens (#89). Every option is a plan Kept already sized: due 1-2 days after payday,
// each instalment within the customer's spare cash. The customer picks one; there's no free date, because a
// date before payday is the promise that breaks. No sign-in and no name, account or case ID on the page.
import { CheckCircledIcon } from "@radix-ui/react-icons";
import { Box, Button, Callout, Card, Flex, Heading, Link, RadioCards, Text } from "@radix-ui/themes";
import { use, useEffect, useState } from "react";
import { MapleMark } from "@/components/bits";
import { api, type PayOffer, type PromiseSizing } from "@/lib/api";

const money = (v: string | number) => new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(Number(v));
const day = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString("en-CA", { weekday: "short", day: "numeric", month: "short" });

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

  useEffect(() => {
    api.payOffer(token).then(
      (o) => {
        setOffer(o);
        setPick(String(o.options[0]?.installments ?? ""));
      },
      (e: Error) => setError(e.message),
    );
  }, [token]);

  async function confirm() {
    setBusy(true);
    try {
      setDone(await api.payChoose(token, Number(pick)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box style={{ width: "100%", maxWidth: 440, margin: "0 auto", padding: "32px 16px", boxSizing: "border-box", overflowWrap: "anywhere" }}>
      <Flex align="center" gap="2" mb="5">
        <MapleMark />
        <Text weight="bold">Maple Bank</Text>
      </Flex>
      {error && <Callout.Root color="red"><Callout.Text>{error}</Callout.Text></Callout.Root>}
      {done && (
        <Card size="3">
          <Flex direction="column" align="center" gap="3" style={{ textAlign: "center" }}>
            <CheckCircledIcon width={32} height={32} color="var(--grass-9)" />
            <Heading size="5">You&apos;re all set</Heading>
            <Text>{describe(done)}</Text>
            <Text size="2" color="gray">The first payment is on {day(done.due_date)}. We&apos;ll remind you the day before each one.</Text>
          </Flex>
        </Card>
      )}
      {offer && !done && (
        <>
          <Heading size="6" mb="1">Pick a plan that works for you</Heading>
          <Text as="p" size="2" color="gray" mb="4">
            {money(offer.amount_due)} is overdue. Every option below is timed for right after your payday and fits what you usually have left after bills.
          </Text>
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
              <Button size="3" mt="4" style={{ width: "100%" }} loading={busy} disabled={!pick} onClick={() => void confirm()}>Confirm this plan</Button>
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
