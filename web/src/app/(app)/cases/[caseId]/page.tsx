"use client";

import { ArrowLeftIcon, ChatBubbleIcon, ReloadIcon } from "@radix-ui/react-icons";
import { Box, Button, Callout, Card, Flex, Grid, Heading, IconButton, Skeleton, Tabs, Text, TextArea, Tooltip } from "@radix-ui/themes";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { AuditTimeline } from "@/components/audit-timeline";
import { CustomerPanel } from "@/components/customer-panel";
import { ExtractionPanel } from "@/components/extraction-panel";
import { Checks, NbaCard } from "@/components/nba-card";
import { ReviewPanel } from "@/components/review-panel";
import { SizingWhatIf } from "@/components/sizing-whatif";
import { ApiError, api, type AuditEvent, type Customer, type NBACard, type NoteExtraction } from "@/lib/api";
import { useServerClock } from "@/lib/clock";
import { useSession } from "@/lib/session";

export default function CasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = use(params);
  const { me } = useSession();
  const { now, health } = useServerClock();
  const [card, setCard] = useState<NBACard | null>(null);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [note, setNote] = useState("");
  const [noting, setNoting] = useState(false);
  const [preset, setPreset] = useState<string | undefined>(undefined);
  const [tab, setTab] = useState("review");
  const [notes, setNotes] = useState<NoteExtraction[]>([]);

  const loadAudit = useCallback(() => {
    if (me) api.audit(me, { caseId }).then(setEvents, () => {});
  }, [me, caseId]);
  const loadNotes = useCallback(() => {
    if (me) api.extractions(caseId, me).then(setNotes, () => setNotes([]));
  }, [me, caseId]);

  useEffect(() => {
    if (!me) return;
    let live = true;
    Promise.all([api.card(caseId, me), api.customer(caseId, me)]).then(
      ([c, cu]) => {
        if (!live) return;
        setCard(c);
        setCustomer(cu);
        setError(null);
        loadAudit();
        loadNotes();
      },
      (e: Error) => {
        if (!live) return;
        const s = e instanceof ApiError ? e.status : 0;
        setError(s === 403 ? `${caseId} isn't in ${me.name}'s queue.` : s === 404 ? `No open case ${caseId}.` : e.message);
      },
    );
    return () => {
      live = false;
    };
  }, [caseId, me, nonce, loadAudit, loadNotes]);

  async function addNote() {
    if (!me || !note.trim()) return;
    setNoting(true);
    try {
      setCard(await api.note(caseId, note.trim(), me));
      setCustomer(await api.customer(caseId, me));
      setNote("");
      loadAudit();
      loadNotes();
    } finally {
      setNoting(false);
    }
  }

  if (!me) return null;
  return (
    <Box>
      <Flex align="center" gap="3" mb="5">
        <Tooltip content="Back to the queue">
          <IconButton variant="ghost" color="gray" asChild>
            <Link href="/queue" aria-label="Back to the queue">
              <ArrowLeftIcon />
            </Link>
          </IconButton>
        </Tooltip>
        <Box>
          <Heading size="6">{customer?.display_name ?? (error ? "Case" : <Skeleton>Customer name</Skeleton>)}</Heading>
          <Text size="1" color="gray" className="tabular">{caseId}</Text>
        </Box>
        <Tooltip content="Recommend again on fresh data">
          <IconButton ml="auto" variant="soft" color="gray" onClick={() => setNonce((n) => n + 1)} aria-label="Refresh">
            <ReloadIcon />
          </IconButton>
        </Tooltip>
      </Flex>

      {error && (
        <Callout.Root color="red">
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      )}
      {!error && !card && (
        <Grid columns={{ initial: "1", md: "3fr 2fr" }} gap="4">
          <Skeleton height="420px" />
          <Skeleton height="420px" />
        </Grid>
      )}
      {card && (
        <Grid columns={{ initial: "1", md: "3fr 2fr" }} gap="4" align="start">
          <Flex direction="column" gap="4">
            <NbaCard card={card} balance={customer ? Number(customer.total_overdue) : undefined} />
            {card.proposal?.sizing && customer && (
              <SizingWhatIf
                key={card.proposal.proposal_id}
                proposal={card.proposal}
                balance={Number(customer.total_overdue)}
                onPropose={(a) => {
                  setPreset(a);
                  setTab("review");
                }}
              />
            )}
            {health?.demo && (
              <Card size="3">
                <Flex align="center" gap="2" mb="2">
                  <ChatBubbleIcon />
                  <Heading size="4">Add an agent note</Heading>
                </Flex>
                <Text as="p" size="2" color="gray" mb="3">
                  In production a note goes through redaction and text extraction (Track C). The demo reads it with simple
                  rules: try &ldquo;customer says shifts were cut at the plant&rdquo;.
                </Text>
                <TextArea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did the customer say?" />
                <Flex justify="end" mt="3">
                  <Button loading={noting} disabled={!note.trim()} onClick={() => void addNote()}>
                    Save note and re-check
                  </Button>
                </Flex>
              </Card>
            )}
            <ExtractionPanel items={notes} agentId={me.userId} demo={!!health?.demo} onSaved={() => setNonce((n) => n + 1)} />
          </Flex>
          <Card size="3" style={{ position: "sticky", top: 84 }}>
            <Tabs.Root value={tab} onValueChange={setTab}>
              <Tabs.List>
                <Tabs.Trigger value="review">Review</Tabs.Trigger>
                <Tabs.Trigger value="customer">Customer</Tabs.Trigger>
                <Tabs.Trigger value="activity">Activity</Tabs.Trigger>
              </Tabs.List>
              <Box pt="4">
                <Tabs.Content value="review">
                  <Flex direction="column" gap="5">
                    {card.proposal ? (
                      <ReviewPanel
                        key={`${card.proposal.proposal_id}-${preset ?? ""}`}
                        presetAmount={preset}
                        proposal={card.proposal}
                        actions={card.probabilities.map((a) => a.action)}
                        me={me}
                        assignedToMe={customer?.assigned_agent_id === me.userId}
                        now={now}
                        onDone={loadAudit}
                      />
                    ) : (
                      <Text color="gray" size="2">Nothing to review: {card.no_action_reason}</Text>
                    )}
                    {card.checks.length > 0 && (
                      <Box>
                        <Text as="div" size="1" weight="medium" color="gray" mb="2">SAFETY CHECKS AT THE PROPOSED TIME</Text>
                        <Checks card={card} />
                      </Box>
                    )}
                    <Text size="1" color="gray">
                      Model {card.model_version} · features as of{" "}
                      {new Date(card.features_as_of).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}
                    </Text>
                  </Flex>
                </Tabs.Content>
                <Tabs.Content value="customer">{customer && <CustomerPanel c={customer} />}</Tabs.Content>
                <Tabs.Content value="activity">
                  <AuditTimeline events={events} />
                </Tabs.Content>
              </Box>
            </Tabs.Root>
          </Card>
        </Grid>
      )}
    </Box>
  );
}
