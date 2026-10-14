"use client";

import {
  BarChartIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  DashboardIcon,
  ExitIcon,
  LayersIcon,
  MixerHorizontalIcon,
  MoonIcon,
  PersonIcon,
  PlayIcon,
  ReaderIcon,
  SunIcon,
} from "@radix-ui/react-icons";
import { Avatar, Box, DropdownMenu, Flex, Spinner, Text, Tooltip } from "@radix-ui/themes";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useSyncExternalStore } from "react";
import { useServerClock } from "@/lib/clock";
import { PERSONAS, can, useSession } from "@/lib/session";
import { useHydrated } from "@/lib/stored";
import { LogoMark, initials } from "./bits";
import { NotificationCenter } from "./notifications";

export const NAV = [
  { href: "/queue", label: "Queue", icon: LayersIcon, blurb: "Today's cases, ranked by expected recovery", show: can.queue },
  { href: "/portfolio", label: "Portfolio", icon: DashboardIcon, blurb: "Tonight's book: where the money is, what works", show: can.portfolio },
  { href: "/approvals", label: "Approvals", icon: CheckCircledIcon, blurb: "Cards waiting for a person to release them", show: can.approvals },
  { href: "/audit", label: "Audit", icon: ReaderIcon, blurb: "Every recommendation, release and override", show: can.audit },
  { href: "/ask", label: "Ask", icon: ChatBubbleIcon, blurb: "Questions in plain English, certified metrics", show: () => true },
  { href: "/bench", label: "Bench", icon: BarChartIcon, blurb: "The evidence: benchmark, model and fairness", show: () => true },
  { href: "/steward", label: "Steward", icon: MixerHorizontalIcon, blurb: "Uncertain customer matches to review", show: can.steward },
  { href: "/demo", label: "Guided demo", icon: PlayIcon, blurb: "One case, start to finish, in six steps", show: () => true },
];

// phones get the bottom tab bar (globals.css, max-width 767px): menus open above it, not beside it
const PHONE = "(max-width: 767px)";
function usePhone() {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(PHONE);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(PHONE).matches,
    () => false,
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { me, signIn, signOut } = useSession();
  const ready = useHydrated();
  const router = useRouter();
  const path = usePathname();
  const { resolvedTheme, setTheme } = useTheme();
  const { now, health } = useServerClock();
  const phone = usePhone();

  useEffect(() => {
    if (ready && !me) router.replace("/signin");
  }, [ready, me, router]);
  if (!ready || !me) {
    // the frame and rail draw at once, so nothing jumps while the session loads
    return (
      <div className="k-frame">
        <nav className="k-rail" aria-label="Main" style={{ viewTransitionName: "k-rail" }}>
          <LogoMark size={44} />
        </nav>
        <main className="k-main">
          <Flex height="60vh" align="center" justify="center">
            <Spinner size="3" />
          </Flex>
        </main>
      </div>
    );
  }
  const items = NAV.filter((n) => n.show(me.role));
  const active = (href: string) => path.startsWith(href) || (href === "/queue" && path.startsWith("/cases"));
  const dark = resolvedTheme === "dark";

  return (
    <div className="k-frame">
      <nav className="k-rail" aria-label="Main" style={{ viewTransitionName: "k-rail" }}>
        <Link href="/" aria-label="Kept: back to the landing page" style={{ marginBottom: 14 }} className="k-rail-logo">
          <LogoMark size={44} />
        </Link>
        {items.map((n) => (
          <Tooltip key={n.href} content={n.label} side="right">
            <Link href={n.href} className="k-rail-btn" aria-label={n.label} aria-current={active(n.href) ? "page" : undefined}>
              {active(n.href) && (
                <motion.span layoutId="rail-active" className="k-rail-active" transition={{ type: "spring", stiffness: 420, damping: 34 }} />
              )}
              <n.icon />
            </Link>
          </Tooltip>
        ))}
        <span className="k-rail-gap" style={{ flex: 1 }} />
        <Tooltip content={dark ? "Light mode" : "Dark mode"} side="right">
          <button className="k-rail-btn k-rail-theme" aria-label="Toggle colour mode" onClick={() => setTheme(dark ? "light" : "dark")}>
            {dark ? <SunIcon /> : <MoonIcon />}
          </button>
        </Tooltip>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <button aria-label={`Account: ${me.name}`} className="k-rail-avatar">
              <Avatar size="3" fallback={initials(me.name)} radius="full" color="ruby" variant="solid" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content
            side={phone ? "top" : "right"}
            align="end"
            sideOffset={phone ? 14 : 8}
            collisionPadding={12}
            className="k-account-menu"
          >
            <DropdownMenu.Label>
              {me.name} · {me.title}
            </DropdownMenu.Label>
            <DropdownMenu.Item onSelect={() => setTheme(dark ? "light" : "dark")}>
              {dark ? <SunIcon /> : <MoonIcon />} {dark ? "Light mode" : "Dark mode"}
            </DropdownMenu.Item>
            <DropdownMenu.Separator />
            <DropdownMenu.Label>Switch persona</DropdownMenu.Label>
            {PERSONAS.map((p) => (
              <DropdownMenu.Item
                key={p.userId}
                disabled={p.name === me.name}
                onSelect={() => {
                  signIn(p);
                  router.push(p.home);
                }}
              >
                <PersonIcon /> {p.name} · {p.title}
              </DropdownMenu.Item>
            ))}
            <DropdownMenu.Separator />
            <DropdownMenu.Item
              color="ruby"
              onSelect={() => {
                signOut();
                router.push("/signin");
              }}
            >
              <ExitIcon /> Sign out
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      </nav>

      <main className="k-main">
        <Flex align="center" justify="between" gap="3" wrap="wrap" mb="5">
          <Flex align="center" gap="3">
            <Link href="/" aria-label="Kept: back to the landing page" className="k-mobile-only">
              <LogoMark size={36} />
            </Link>
            <Box>
            <Text as="div" size="1" color="gray">
              {me.title}
            </Text>
            <Text as="div" size="3" weight="medium">
              {me.name}
            </Text>
            </Box>
          </Flex>
          <Flex align="center" gap="2">
            <NotificationCenter me={me} />
            {health?.demo && now && (
              <Tooltip content="Demo mode runs on a business-hours clock so releases can pass the real calling-hours check.">
                <span className="k-badge" style={{ height: 44, padding: "0 16px", borderRadius: 999, fontWeight: 500, fontSize: 13 }}>
                  Demo clock · {now.toLocaleString("en-CA", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "America/Toronto" })} Toronto
                </span>
              </Tooltip>
            )}
            {!path.startsWith("/demo") && (
              <Link href="/demo" className="k-strong-btn k-demo-btn">
                <PlayIcon /> <span className="k-desktop-only">Guided demo</span>
              </Link>
            )}
          </Flex>
        </Flex>
        {children}
      </main>
    </div>
  );
}
