"use client";

import { SectionTitle } from "@/components/page-header";
import { ArrowLeftIcon, ChatBubbleIcon, ReloadIcon } from "@radix-ui/react-icons";
import { Box, Button, Callout, Card, Flex, Grid, Skeleton, Tabs, Text, TextArea, Tooltip } from "@radix-ui/themes";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { use, useCallback, useEffect, useState } from "react";
import { CustomerPanel } from "@/components/customer-panel";
import { Checks, NbaCard } from "@/components/nba-card";
import { ReviewPanel } from "@/components/review-panel";
import { SizingWhatIf } from "@/components/sizing-whatif";
import { TierBadge } from "@/components/bits";
import { BriefCard } from "@/components/brief-card";
import { HistoryPanel, WhyChart } from "@/components/case-insights";
import { ApiError, api, money, type AuditEvent, type CaseHistory, type CallOut, type Customer, type NBACard, type NoteExtraction } from "@/lib/api";
import { useServerClock } from "@/lib/clock";
import { invalidate, keys, load, peek, set } from "@/lib/live";
import { useSession } from "@/lib/session";

// below the fold or behind a tab: their code loads when they first render
const AuditTimeline = dynamic(() => import("@/components/audit-timeline").then((m) => m.AuditTimeline), { loading: () => <Skeleton height="160px" /> });
const CallsPanel = dynamic(() => import("@/components/calls-panel").then((m) => m.CallsPanel), { loading: () => <Skeleton height="160px" /> });
const ExtractionPanel = dynamic(() => import("@/components/extraction-panel").then((m) => m.ExtractionPanel), {
  loading: () => <Skeleton height="160px" />,
});

const TABS = ["overview", "review", "activity"];

export default function CasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = use(params);
  const { me } = useSession();
  const { now, health } = useServerClock();
  const [card, setCard] = useState<NBACard | null>(() => (me ? (peek<NBACard>(keys.card(caseId, me.userId)) ?? null) : null));
  const [customer, setCustomer] = useState<Customer | null>(() => (me ? (peek<Customer>(keys.customer(caseId, me.userId)) ?? null) : null));
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [note, setNote] = useState("");
  const [noting, setNoting] = useState(false);
  const [preset, setPreset] = useState<string | undefined>(undefined);
  // a case opens on its overview; a tab in the URL (?tab=review, ?tab=activity) still deep-links
  const asked = useSearchParams().get("tab");
  const [tab, setTabState] = useState(asked && TABS.includes(asked) ? asked : "overview");
  const setTab = (t: string) => {
    setTabState(t);
    const u = new URL(window.location.href);
    if (t === "overview") u.searchParams.delete("tab");
    else u.searchParams.set("tab", t);
    window.history.replaceState(window.history.state, "", u);
  };
  const [notes, setNotes] = useState<NoteExtraction[]>([]);
  const [calls, setCalls] = useState<CallOut[]>([]);
  const [history, setHistory] = useState<CaseHistory | null>(() => (me ? (peek<CaseHistory>(keys.history(caseId, me.userId)) ?? null) : null));

  const loadAudit = useCallback(() => {
    if (me) api.audit(me, { caseId }).then(setEvents, () => {});
  }, [me, caseId]);
  const demo = !!health?.demo;
  const loadNotes = useCallback(() => {
    if (me && health) api.extractions(caseId, me, demo).then(setNotes, () => setNotes([]));
  }, [me, caseId, health, demo]);
  // C: a cease the model suggested stops nothing until the agent confirms it
  const ceaseToConfirm = notes.find((n) => n.extraction.cease_request.value && !n.extraction.confirmed_by_agent_id);
  const [confirming, setConfirming] = useState(false);
  const confirmCease = async (sourceId: string) => {
    if (!me) return;
    setConfirming(true);
    try {
      await api.confirmExtraction(sourceId, me.userId, {}, demo);
      setNonce((n) => n + 1);
    } finally {
      setConfirming(false);
    }
  };

  useEffect(() => {
    if (!me) return;
    let live = true;
    // a hover in the queue may have fetched these already; after a change (nonce) always fetch again
    const fresh = nonce ? { fresh: 0 } : undefined;
    Promise.all([
      load(keys.card(caseId, me.userId), () => api.card(caseId, me), fresh),
      load(keys.customer(caseId, me.userId), () => api.customer(caseId, me), fresh),
    ]).then(
      ([c, cu]) => {
        if (!live) return;
        setCard(c);
        setCustomer(cu);
        setError(null);
        loadAudit();
        loadNotes();
        if (!demo) api.calls(caseId, me).then(setCalls, () => setCalls([])); // no recordings here: no panel
        if (!demo) load(keys.history(caseId, me.userId), () => api.history(caseId, me)).then(setHistory, () => setHistory(null));
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
  }, [caseId, me, nonce, loadAudit, loadNotes, demo]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loadBrief = useCallback(() => api.caseBrief(caseId, me!), [caseId, me?.userId, nonce]);

  async function addNote() {
    if (!me || !note.trim()) return;
    setNoting(true);
    try {
      const c = await api.note(caseId, note.trim(), me);
      setCard(c);
      set(keys.card(caseId, me.userId), c);
      const cu = await load(keys.customer(caseId, me.userId), () => api.customer(caseId, me), { fresh: 0 });
      setCustomer(cu);
      invalidate(keys.queue(me.userId));
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
      <Flex align="end" gap="4" mb="5" wrap="wrap">
        <Tooltip content="Back to the queue">
          <Link href="/queue" className="k-round-btn" aria-label="Back to the queue">
            <ArrowLeftIcon />
          </Link>
        </Tooltip>
        <Box style={{ minWidth: 0 }}>
          <Flex gap="2" align="center" wrap="wrap" mb="2">
            <span className="k-badge tabular">{caseId}</span>
            {customer && <span className="k-badge">{customer.max_dpd} days past due</span>}
            {customer && <span className="k-badge">{money(customer.total_overdue, true)} overdue</span>}
            {card?.proposal && <TierBadge tier={card.proposal.tier} long={false} />}
          </Flex>
          <h1 className="k-display">{customer?.display_name ?? (error ? "Case" : <Skeleton>Customer name</Skeleton>)}</h1>
        </Box>
        <Tooltip content="Recommend again on fresh data">
          <button className="k-round-btn" style={{ marginLeft: "auto" }} onClick={() => setNonce((n) => n + 1)} aria-label="Refresh">
            <ReloadIcon />
          </button>
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
            <BriefCard load={loadBrief} eyebrow="Case brief · local model, every claim cited" title="Before you act" />
            <NbaCard card={card} balance={customer ? Number(customer.total_overdue) : undefined} />
            <WhyChart card={card} />
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
            {ceaseToConfirm && (
              <Callout.Root color="red" variant="surface">
                <Callout.Text>
                  <Flex align="center" justify="between" gap="3" wrap="wrap">
                    <span>
                      Possible cease request in a note: &ldquo;
                      {ceaseToConfirm.extraction.cease_request.evidence?.quote ?? ceaseToConfirm.note.slice(0, 80)}
                      &rdquo;. Contact stops once you confirm it.
                    </span>
                    <Button
                      size="1"
                      color="red"
                      loading={confirming}
                      disabled={me.userId !== customer?.assigned_agent_id}
                      onClick={() => void confirmCease(ceaseToConfirm.extraction.source_id)}
                    >
                      Confirm cease request
                    </Button>
                  </Flex>
                </Callout.Text>
              </Callout.Root>
            )}
            {health && (
              <Card size="3">
                <SectionTitle eyebrow="Agent" title="Add an agent note" icon={<ChatBubbleIcon />} mb="2" />
                <Text as="p" size="2" color="gray" mb="3">
                  {demo ? (
                    <>
                      In production a note goes through redaction and text extraction (Track C). The demo reads it with
                      simple rules: try &ldquo;customer says shifts were cut at the plant&rdquo;.
                    </>
                  ) : (
                    <>The note is redacted, then read by the extraction model (a few seconds); the card re-checks after.</>
                  )}
                </Text>
                <TextArea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did the customer say?" />
                <Flex justify="end" mt="3">
                  <Button loading={noting} disabled={!note.trim()} onClick={() => void addNote()}>
                    Save note and re-check
                  </Button>
                </Flex>
              </Card>
            )}
            <ExtractionPanel items={notes} agentId={me.userId} demo={demo} onSaved={() => setNonce((n) => n + 1)} />
            <CallsPanel calls={calls} who={me} />
            {history && <HistoryPanel h={history} />}
          </Flex>
          <Card size="3" style={{ position: "sticky", top: 84 }}>
            <Tabs.Root value={tab} onValueChange={setTab}>
              <Tabs.List>
                <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
                <Tabs.Trigger value="review">Review</Tabs.Trigger>
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
                        <Text as="div" className="k-eyebrow" mb="2">Safety checks at the proposed time</Text>
                        <Checks card={card} />
                      </Box>
                    )}
                    <Text size="1" color="gray">
                      Model {card.model_version} · features as of{" "}
                      {new Date(card.features_as_of).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}
                    </Text>
                  </Flex>
                </Tabs.Content>
                <Tabs.Content value="overview">{customer ? <CustomerPanel c={customer} /> : <Skeleton height="320px" />}</Tabs.Content>
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
