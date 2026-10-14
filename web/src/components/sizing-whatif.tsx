"use client";

import { SectionTitle } from "./page-header";
import { Badge, Box, Button, Card, Flex, Slider, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { money, type Proposal } from "@/lib/api";
import { spring } from "./motion";

/** Drag an amount and see, live, whether it still fits spare cash and how many payments it means. */
export function SizingWhatIf({ proposal, balance, onPropose }: { proposal: Proposal; balance: number; onPropose: (amount: string) => void }) {
  const s = proposal.sizing!;
  const spare = Number(s.spare_cash_estimate);
  const max = Math.max(spare * 2, Number(s.amount) * 1.5, 50);
  const [amount, setAmount] = useState(Number(s.amount));
  const payments = Math.ceil(balance / Math.max(amount, 1));
  const fits = amount <= spare;
  const headroom = spare - amount;
  return (
    <Card size="3">
      <Flex justify="between" align="center" mb="3">
        <SectionTitle eyebrow="Promise sizing" title="Payment plan options" mb="0" />
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={String(fits)} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }} transition={spring}>
            <Badge size="2" color={fits ? "grass" : "red"} variant="soft">{fits ? "fits spare cash" : "above spare cash"}</Badge>
          </motion.span>
        </AnimatePresence>
      </Flex>
      <Flex align="baseline" gap="2">
        <Text size="8" weight="bold" className="serif tabular">{money(amount)}</Text>
        <Text color="gray">a pay period · {payments} payment{payments === 1 ? "" : "s"} to clear {money(balance)}</Text>
      </Flex>
      <Box my="4" style={{ position: "relative" }}>
        <Slider value={[amount]} min={10} max={Math.round(max)} step={5} onValueChange={([v]) => setAmount(v)} color={fits ? "grass" : "red"} aria-label="Promise amount" />
        <div title={`Spare cash ~${money(spare)}`} style={{ position: "absolute", top: -6, bottom: -6, left: `${((spare - 10) / (max - 10)) * 100}%`, width: 2, background: "var(--gray-12)", opacity: 0.5, borderRadius: 1, pointerEvents: "none" }} />
      </Box>
      <Text as="p" size="2" color="gray">
        {fits
          ? `${money(headroom)} of headroom under ~${money(spare)} spare cash: the kind of promise people keep.`
          : `${money(-headroom)} over ~${money(spare)} spare cash: promises sized like this tend to break.`}
      </Text>
      <Flex justify="end" mt="3">
        <Button variant="soft" disabled={!fits || amount === Number(s.amount)} onClick={() => onPropose(amount.toFixed(2))}>
          Propose {money(amount)} in review
        </Button>
      </Flex>
    </Card>
  );
}
