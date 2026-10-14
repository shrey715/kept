"use client";

import { Badge, Box, Code, DataList, Flex, Text } from "@radix-ui/themes";
import { motion } from "motion/react";
import { humanize, money, type Customer } from "@/lib/api";
import { Meter, spring } from "./motion";

export const SYSTEM_COLOR = { crm: "ruby", card: "iris", loan: "cyan", deposit: "grass", collections: "amber", bureau: "gray" } as const;

export function CustomerPanel({ c }: { c: Customer }) {
  const conf = c.match_confidence_min ?? null;
  return (
    <Flex direction="column" gap="4">
      <Box>
        <Text size="1" color="gray" weight="medium">Golden ID</Text>
        <Flex align="center" gap="2">
          <Code size="4" variant="ghost" weight="bold">{c.golden_customer_id}</Code>
          <Badge color={c.match_review_status === "auto" ? "grass" : "amber"} variant="soft">{humanize(c.match_review_status)}</Badge>
        </Flex>
        {conf !== null && (
          <Box mt="2">
            <Flex justify="between" mb="1">
              <Text size="1" color="gray">Weakest match in the cluster</Text>
              <Text size="1" className="tabular">{Math.round(conf * 100)}%</Text>
            </Flex>
            <Meter value={conf} />
          </Box>
        )}
      </Box>
      <Box>
        <Text size="1" color="gray" weight="medium">Resolved from {c.source_keys.length} systems</Text>
        <Flex direction="column" gap="2" mt="2">
          {c.source_keys.map((k, i) => (
            <motion.div key={`${k.system}-${k.key}`} initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} transition={{ ...spring, delay: i * 0.08 }}>
              <Flex align="center" gap="2">
                <Badge color={SYSTEM_COLOR[k.system]} variant="soft" style={{ minWidth: 92, justifyContent: "center" }}>{k.system}</Badge>
                <Code variant="ghost">{k.key}</Code>
              </Flex>
            </motion.div>
          ))}
        </Flex>
      </Box>
      <DataList.Root size="2">
        <DataList.Item>
          <DataList.Label>Name</DataList.Label>
          <DataList.Value>{c.display_name ?? "—"}</DataList.Value>
        </DataList.Item>
        <DataList.Item>
          <DataList.Label>Phone</DataList.Label>
          <DataList.Value className="tabular">{c.primary_phone_e164 ?? "—"}</DataList.Value>
        </DataList.Item>
        <DataList.Item>
          <DataList.Label>Email</DataList.Label>
          <DataList.Value>{c.email ?? "—"}</DataList.Value>
        </DataList.Item>
        <DataList.Item>
          <DataList.Label>Overdue</DataList.Label>
          <DataList.Value className="tabular">{money(c.total_overdue, true)} · {c.max_dpd} days · {c.current_bucket}</DataList.Value>
        </DataList.Item>
        <DataList.Item>
          <DataList.Label>Consent</DataList.Label>
          <DataList.Value>
            <Flex gap="1" wrap="wrap">
              {(["call", "sms", "email", "push"] as const).map((ch) => (
                <Badge key={ch} color={c.contact_permissions[ch] ? "grass" : "gray"} variant={c.contact_permissions[ch] ? "soft" : "outline"}>
                  {ch}
                </Badge>
              ))}
            </Flex>
          </DataList.Value>
        </DataList.Item>
        <DataList.Item>
          <DataList.Label>Hardship</DataList.Label>
          <DataList.Value>
            <Badge color={c.hardship_status === "none" ? "gray" : "amber"} variant="soft">{c.hardship_status}</Badge>
          </DataList.Value>
        </DataList.Item>
        <DataList.Item>
          <DataList.Label>Next payday</DataList.Label>
          <DataList.Value>{c.expected_next_payroll_date ?? "unknown"} · {humanize(c.payroll_frequency_detected ?? "unknown")}</DataList.Value>
        </DataList.Item>
      </DataList.Root>
      <Text size="1" color="gray">Personal data is masked for every role except compliance.</Text>
    </Flex>
  );
}
