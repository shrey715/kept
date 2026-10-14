"use client";

import { Badge, Flex, Text } from "@radix-ui/themes";
import type { Tier } from "@/lib/api";

const TIER: Record<Tier, { color: "grass" | "amber" | "plum" | "gray"; label: string; who: string }> = {
  green: { color: "grass", label: "Green", who: "team lead batch" },
  amber: { color: "amber", label: "Amber", who: "assigned agent" },
  red: { color: "plum", label: "Red", who: "specialist + second person" },
  blocked: { color: "gray", label: "Blocked", who: "nobody" },
};

export function TierBadge({ tier, size = "2", long = true }: { tier: Tier; size?: "1" | "2" | "3"; long?: boolean }) {
  const t = TIER[tier];
  return (
    <Badge color={t.color} size={size} variant="soft" radius="full">
      {t.label}
      {long && <Text weight="regular"> · {t.who}</Text>}
    </Badge>
  );
}

export const tierColor = (tier: Tier) => TIER[tier].color;

/** The pastel tint a tier wears (globals.css .t-*): Red rose, Amber butter, Green mint. */
export const tierTint = (tier: Tier) => ({ red: "rose", amber: "butter", green: "mint", blocked: "ice" } as const)[tier];

const LEAF =
  "M12 2l1.6 3.6 2.3-1.1-.6 4.6 3.1-2.2.7 2.5 2.9-.6-1.5 3.6 1.5.9-4.8 3.8.6 1.7-4.3-.6V22h-1V18.2l-4.3.6.6-1.7L4 13.3l1.5-.9L4 8.8l2.9.6.7-2.5 3.1 2.2-.6-4.6 2.3 1.1z";

export function MapleMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="var(--accent-9)">
      <path d={LEAF} />
    </svg>
  );
}

/** The app icon (src/app/icon.svg) as a component: an ink tile, a hairline frame, the maple leaf. */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden style={{ flex: "none", display: "block" }}>
      <rect width="32" height="32" rx="9" fill="#1c1917" />
      <rect x="2.25" y="2.25" width="27.5" height="27.5" rx="7" fill="none" stroke="#faf7f2" strokeOpacity=".28" strokeWidth="1.5" />
      <path transform="translate(6.4 6.2) scale(.8)" fill="#e5293f" d={LEAF} />
    </svg>
  );
}

export function Wordmark() {
  return (
    <Flex align="center" gap="2">
      <LogoMark size={30} />
      <Text size="5" weight="medium" style={{ letterSpacing: "-0.03em" }}>
        Kept
      </Text>
    </Flex>
  );
}

export function initials(name: string) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("");
}
