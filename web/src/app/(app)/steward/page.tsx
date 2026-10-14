"use client";

import { Button, Callout, Card, Code, Flex, Heading, Skeleton, Spinner, Text } from "@radix-ui/themes";
import { motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Rise, Stagger, spring } from "@/components/motion";
import { ApiError, api, type StewardItem } from "@/lib/api";
import { useSession } from "@/lib/session";

const PAGE = 50; // ponytail: pages append as you scroll; a windowed list if one session ever scrolls through thousands

export default function StewardPage() {
  const { me } = useSession();
  const [items, setItems] = useState<StewardItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, string>>({});
  const loading = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);

  const more = useCallback(async () => {
    if (loading.current || (items && items.length >= total && total > 0)) return;
    loading.current = true;
    try {
      const page = await api.stewardQueue(items?.length ?? 0, PAGE);
      setItems((xs) => [...(xs ?? []), ...page.items]);
      setTotal(page.total);
    } catch (e) {
      setError(e instanceof ApiError && e.status >= 500 ? "The match review queue isn't connected." : (e as Error).message);
    } finally {
      loading.current = false;
    }
  }, [items, total]);

  useEffect(() => {
    if (items === null) void more();
  }, [items, more]);

  // the next page loads while the last cards are still about two screens away
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((es) => es[0].isIntersecting && void more(), { rootMargin: "1600px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [more]);

  async function resolve(id: string, verdict: string) {
    if (!me) return;
    setDone((d) => ({ ...d, [id]: verdict === "merge" ? "merged" : "split" })); // optimistic; the server's answer replaces it
    try {
      const r = await api.stewardResolve(id, verdict, me.userId);
      setDone((d) => ({ ...d, [id]: r.status }));
    } catch (e) {
      setDone((d) => ({ ...d, [id]: `error: ${(e as Error).message}` }));
    }
  }

  const all = items !== null && items.length >= total;
  return (
    <Stagger>
      <Rise>
        <Heading size="8">Match review</Heading>
        <Text color="gray" size="2">
          Uncertain matches wait here before two records become one golden ID.
          {total > 0 && <> {total.toLocaleString("en-CA")} to review, oldest first.</>}
        </Text>
      </Rise>
      {error && (
        <Rise>
          <Callout.Root color="gray" mt="5">
            <Callout.Text>{error}</Callout.Text>
          </Callout.Root>
        </Rise>
      )}
      {!items && !error && <Skeleton height="200px" mt="5" />}
      {items && (
        <Flex direction="column" gap="3" mt="5">
          {items.length === 0 && <Text color="gray">Nothing to review.</Text>}
          {items.map((i, n) => (
            <motion.div
              key={i.item_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0, transition: { ...spring, delay: (n % PAGE) * 0.02 } }}
              style={{ contentVisibility: "auto", containIntrinsicSize: "auto 76px" }}
            >
              <Card size="2">
                <Flex align="center" gap="4" wrap="wrap">
                  <Flex direction="column" style={{ flex: 1 }}>
                    <Text>
                      <Code>{i.left_key}</Code> vs <Code>{i.right_key}</Code>
                    </Text>
                    <Text size="1" color="gray">
                      score {i.score.toFixed(2)} · {i.reasons.join("; ")}
                    </Text>
                  </Flex>
                  {done[i.item_id] ? (
                    <Text size="2" color="gray">
                      {done[i.item_id]}
                    </Text>
                  ) : (
                    <Flex gap="2">
                      <Button variant="soft" onClick={() => void resolve(i.item_id, "merge")}>
                        Same person
                      </Button>
                      <Button variant="soft" color="gray" onClick={() => void resolve(i.item_id, "split")}>
                        Different people
                      </Button>
                    </Flex>
                  )}
                </Flex>
              </Card>
            </motion.div>
          ))}
          <div ref={sentinel} />
          {!all && (
            <Flex justify="center" py="4" gap="2" align="center">
              <Spinner /> <Text size="1" color="gray">Showing {items.length.toLocaleString("en-CA")} of {total.toLocaleString("en-CA")}</Text>
            </Flex>
          )}
        </Flex>
      )}
    </Stagger>
  );
}
