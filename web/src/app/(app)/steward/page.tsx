"use client";

import { Button, Callout, Card, Code, Flex, Heading, Skeleton, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { Rise, Stagger, spring } from "@/components/motion";
import { ApiError, api, type StewardItem } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function StewardPage() {
  const { me } = useSession();
  const [items, setItems] = useState<StewardItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, string>>({});

  useEffect(() => {
    api.stewardQueue().then(setItems, (e: Error) =>
      setError(e instanceof ApiError && e.status >= 500 ? "The match review queue isn't connected yet (Track A's steward service)." : e.message),
    );
  }, []);

  async function resolve(id: string, verdict: string) {
    if (!me) return;
    try {
      const r = await api.stewardResolve(id, verdict, me.userId);
      setDone((d) => ({ ...d, [id]: r.status }));
    } catch (e) {
      setDone((d) => ({ ...d, [id]: `error: ${(e as Error).message}` }));
    }
  }

  return (
    <Stagger>
      <Rise>
        <Heading size="8">Match review</Heading>
        <Text color="gray" size="2">Uncertain matches wait here before two records become one golden ID.</Text>
      </Rise>
      {error && (
        <Rise>
          <Callout.Root color="gray" mt="5"><Callout.Text>{error}</Callout.Text></Callout.Root>
        </Rise>
      )}
      {!items && !error && <Skeleton height="200px" mt="5" />}
      {items && (
        <Flex direction="column" gap="3" mt="5">
          {items.length === 0 && <Text color="gray">Nothing to review.</Text>}
          <AnimatePresence>
            {items.map((i, n) => (
              <motion.div key={i.item_id} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0, transition: { ...spring, delay: n * 0.04 } }}>
                <Card size="2">
                  <Flex align="center" gap="4" wrap="wrap">
                    <Flex direction="column" style={{ flex: 1 }}>
                      <Text><Code>{i.left_key}</Code> vs <Code>{i.right_key}</Code></Text>
                      <Text size="1" color="gray">score {i.score.toFixed(2)} · {i.reasons.join("; ")}</Text>
                    </Flex>
                    {done[i.item_id] ? (
                      <Text size="2" color="gray">{done[i.item_id]}</Text>
                    ) : (
                      <Flex gap="2">
                        <Button variant="soft" onClick={() => void resolve(i.item_id, "merge")}>Same person</Button>
                        <Button variant="soft" color="gray" onClick={() => void resolve(i.item_id, "split")}>Different people</Button>
                      </Flex>
                    )}
                  </Flex>
                </Card>
              </motion.div>
            ))}
          </AnimatePresence>
        </Flex>
      )}
    </Stagger>
  );
}
