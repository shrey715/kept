"use client";

// The case's recorded calls, read on this machine: Whisper's transcript of the recording, then the same redaction
// and extraction a typed note gets, with the words each signal relied on highlighted. Shown for reference: the card
// already reads the same call from the bank's transcript, so these never change a decision.
import { SectionTitle } from "./page-header";
import { SpeakerLoudIcon } from "@radix-ui/react-icons";
import { Badge, Box, Card, Flex, Text } from "@radix-ui/themes";
import { type CallOut, api, humanize } from "@/lib/api";
import { FIELDS, Highlighted } from "./extraction-panel";

type Who = Parameters<typeof api.calls>[1];

const minutes = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function Found({ c }: { c: CallOut }) {
  const ex = c.extraction;
  if (!ex) return <Text size="1" color="gray">The model couldn&apos;t read this call; the transcript is below.</Text>;
  const hits = FIELDS.filter((f) => {
    const v = ex[f.key].value;
    return v !== null && v !== false && v !== "none";
  });
  if (!hits.length) return <Text size="1" color="gray">Nothing to flag in this call.</Text>;
  return (
    <Flex gap="2" wrap="wrap">
      {hits.map((f) => {
        const v = ex[f.key].value;
        return (
          <Badge key={f.key} color={f.color as never} variant="soft">
            {f.label}
            {typeof v === "string" ? `: ${humanize(v)}` : ""}
          </Badge>
        );
      })}
    </Flex>
  );
}

export function CallsPanel({ calls, who }: { calls: CallOut[]; who: Who }) {
  if (!calls.length) return null;
  return (
    <Card size="3">
      <SectionTitle eyebrow="Calls" title="Call recordings" icon={<SpeakerLoudIcon />} mb="2" />
      <Text as="p" size="2" color="gray" mb="4">
        Transcribed from the recording on this machine (nothing leaves it), then read like a note. For reference: the
        card reads the same call from the bank&apos;s transcript.
      </Text>
      <Flex direction="column" gap="5">
        {calls.map((c) => (
          <Box key={c.voice_sample_id}>
            <Flex justify="between" align="baseline" mb="2">
              <Text size="2" weight="bold">
                {new Date(c.call_start).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}
              </Text>
              <Text size="1" color="gray">{minutes(c.duration_sec)}</Text>
            </Flex>
            <audio controls preload="none" src={api.callAudioUrl(c.voice_sample_id, who)} style={{ width: "100%" }}>
              <track kind="captions" />
            </audio>
            <Box my="2">
              <Found c={c} />
            </Box>
            {c.extraction ? <Highlighted note={c.transcript} ex={c.extraction} /> : <Text as="p" size="2">{c.transcript}</Text>}
          </Box>
        ))}
      </Flex>
    </Card>
  );
}
