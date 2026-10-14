"use client";

import { Box, Flex, Text } from "@radix-ui/themes";
import gsap from "gsap";
import { SplitText } from "gsap/SplitText";
import { useLayoutEffect, useRef } from "react";

gsap.registerPlugin(SplitText);

/** Words rise out of a line mask when the element mounts (GSAP SplitText); still under reduced motion. */
export function useSplitReveal<T extends HTMLElement>(deps: unknown[] = []) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let undo = () => {};
    let live = true;
    el.style.visibility = "hidden"; // no flash of the unsplit title while fonts load
    void document.fonts.ready.then(() => {
      if (!live) return;
      const split = SplitText.create(el, { type: "lines,words", mask: "lines", linesClass: "k-line" });
      el.style.visibility = "";
      const tween = gsap.from(split.words, { yPercent: 115, opacity: 0, duration: 0.8, ease: "expo.out", stagger: 0.045 });
      undo = () => {
        tween.kill();
        split.revert();
      };
    });
    return () => {
      live = false;
      el.style.visibility = "";
      undo();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

/** Every workspace page opens the same way: an icon chip and label, a display title, one line of context, actions. */
export function PageHeader({
  icon,
  eyebrow,
  title,
  sub,
  actions,
}: {
  icon: React.ReactNode;
  eyebrow: string;
  title: string;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  const ref = useSplitReveal<HTMLHeadingElement>([title]);
  return (
    <Flex justify="between" align="end" gap="4" wrap="wrap" mb="5">
      <Box style={{ maxWidth: 940 }}>
        <Flex align="center" gap="3" mb="3">
          <span className="k-chip">{icon}</span>
          <Text size="2" weight="medium">
            {eyebrow}
          </Text>
        </Flex>
        <h1 ref={ref} className="k-display">
          {title}
        </h1>
        {sub && (
          <Text as="p" size="3" color="gray" mt="3" style={{ maxWidth: 640, lineHeight: 1.5 }}>
            {sub}
          </Text>
        )}
      </Box>
      {actions && (
        <Flex gap="2" align="center" wrap="wrap">
          {actions}
        </Flex>
      )}
    </Flex>
  );
}

/** A dashboard section's heading: a small maple label over a display-font title, an optional icon chip and aside. */
export function SectionTitle({
  eyebrow,
  title,
  icon,
  aside,
  mb = "4",
}: {
  eyebrow: string;
  title: React.ReactNode;
  icon?: React.ReactNode;
  aside?: React.ReactNode;
  mb?: "0" | "1" | "2" | "3" | "4" | "5";
}) {
  return (
    <Flex align="center" gap="3" mb={mb} wrap="wrap">
      {icon && <span className="k-chip">{icon}</span>}
      <Box style={{ minWidth: 0 }}>
        <div className="k-eyebrow">{eyebrow}</div>
        <h2 className="k-h2">{title}</h2>
      </Box>
      {aside && <Box ml="auto">{aside}</Box>}
    </Flex>
  );
}
