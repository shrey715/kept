"use client";

import { MagicWandIcon } from "@radix-ui/react-icons";
import { Box, Flex, HoverCard, Skeleton, Text } from "@radix-ui/themes";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import type { Brief } from "@/lib/api";
import { SectionTitle } from "./page-header";

/** A brief the model wrote over numbered sources: each bullet shows its sources; hover one to read it. */
export function BriefCard({ load, eyebrow, title }: { load: () => Promise<Brief>; eyebrow: string; title: string }) {
  const [b, setB] = useState<Brief | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    load().then(
      (x) => live && setB(x),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [load]);
  if (failed) return null;
  const by = new Map((b?.sources ?? []).map((s) => [s.id, s]));
  return (
    <div className="k-card k-brief" style={{ padding: 22 }}>
      <SectionTitle eyebrow={eyebrow} title={title} icon={<MagicWandIcon />} mb="3" />
      {!b ? (
        <Flex direction="column" gap="2">
          <Skeleton height="18px" />
          <Skeleton height="18px" width="85%" />
          <Skeleton height="18px" width="70%" />
        </Flex>
      ) : (
        <>
          <ol className="k-brief-list">
            {b.bullets.map((x, i) => (
              <motion.li key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0, transition: { delay: i * 0.08 } }}>
                <Text size="3" style={{ lineHeight: 1.5 }}>
                  {x.text}
                </Text>
                <span className="k-brief-cites">
                  {x.cites.map((c) => {
                    const s = by.get(c);
                    return (
                      <HoverCard.Root key={c}>
                        <HoverCard.Trigger>
                          <span className="k-cite" data-kind={s?.kind}>
                            {c}
                          </span>
                        </HoverCard.Trigger>
                        <HoverCard.Content size="1" maxWidth="340px">
                          <div className="k-eyebrow">{s?.kind === "quote" ? "Quoted" : "Computed by Kept"}</div>
                          <Text as="div" size="1" color="gray" mb="1">
                            {s?.label}
                          </Text>
                          <Text as="div" size="2">
                            {s?.kind === "quote" ? `“${s.text}”` : s?.text}
                          </Text>
                        </HoverCard.Content>
                      </HoverCard.Root>
                    );
                  })}
                </span>
              </motion.li>
            ))}
          </ol>
          <Box mt="3">
            <Text size="1" color="gray">
              {b.model
                ? `Written by ${b.model.replace(/^(ollama|llamacpp|gemini)\//, "")} on this machine · every number checked against what it cites`
                : "Template brief (the model was unavailable) · built from the same sources"}
              {b.dropped > 0 && ` · ${b.dropped} bullet${b.dropped === 1 ? "" : "s"} dropped by the check`}
            </Text>
          </Box>
        </>
      )}
    </div>
  );
}
