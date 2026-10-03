"use client";

import { ExitIcon, MoonIcon, PersonIcon, SunIcon } from "@radix-ui/react-icons";
import { Avatar, Badge, Box, Container, DropdownMenu, Flex, IconButton, Spinner, Text, Tooltip } from "@radix-ui/themes";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect } from "react";
import { useServerClock } from "@/lib/clock";
import { PERSONAS, can, useSession } from "@/lib/session";
import { useHydrated } from "@/lib/stored";
import { Wordmark, initials } from "./bits";

const NAV = [
  { href: "/queue", label: "Queue", show: can.queue },
  { href: "/approvals", label: "Approvals", show: can.approvals },
  { href: "/audit", label: "Audit", show: can.audit },
  { href: "/ask", label: "Ask", show: () => true },
  { href: "/steward", label: "Steward", show: can.steward },
  { href: "/demo", label: "Guided demo", show: () => true },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { me, signIn, signOut } = useSession();
  const ready = useHydrated();
  const router = useRouter();
  const path = usePathname();
  const { resolvedTheme, setTheme } = useTheme();
  const { now, health } = useServerClock();

  useEffect(() => {
    if (ready && !me) router.replace("/signin");
  }, [ready, me, router]);
  if (!ready || !me) {
    return (
      <Flex height="100vh" align="center" justify="center">
        <Spinner size="3" />
      </Flex>
    );
  }
  const items = NAV.filter((n) => n.show(me.role));
  const active = (href: string) => path.startsWith(href) || (href === "/queue" && path.startsWith("/cases"));

  return (
    <Box>
      <Box
        position="sticky"
        top="0"
        className="glass"
        style={{ zIndex: 20, borderBottom: "1px solid var(--gray-a4)", background: "color-mix(in srgb, var(--color-panel-solid) 78%, transparent)" }}
      >
        <Container size="4" px="4">
          <Flex align="center" gap="5" py="3" wrap="wrap">
            <Link href={me.home} style={{ color: "inherit", textDecoration: "none" }}>
              <Wordmark />
            </Link>
            <Flex gap="1" asChild>
              <nav aria-label="Main">
                {items.map((n) => (
                  <Link key={n.href} href={n.href} style={{ position: "relative", textDecoration: "none" }} aria-current={active(n.href) ? "page" : undefined}>
                    {active(n.href) && (
                      <motion.span
                        layoutId="nav-pill"
                        transition={{ type: "spring", stiffness: 420, damping: 34 }}
                        style={{ position: "absolute", inset: 0, borderRadius: "var(--radius-3)", background: "var(--accent-a3)" }}
                      />
                    )}
                    <Text as="span" size="2" weight={active(n.href) ? "medium" : "regular"} color={active(n.href) ? "ruby" : "gray"} style={{ position: "relative", display: "block", padding: "6px 12px" }}>
                      {n.label}
                    </Text>
                  </Link>
                ))}
              </nav>
            </Flex>
            <Flex ml="auto" align="center" gap="3">
              {health?.demo && now && (
                <Tooltip content="Demo mode runs on a business-hours clock so releases can pass the real calling-hours check.">
                  <Badge variant="surface" color="gray" radius="full" size="2">
                    <span className="tabular">
                      Demo clock · {now.toLocaleString("en-CA", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "America/Toronto" })} Toronto
                    </span>
                  </Badge>
                </Tooltip>
              )}
              <Tooltip content={resolvedTheme === "dark" ? "Light mode" : "Dark mode"}>
                <IconButton variant="ghost" color="gray" aria-label="Toggle colour mode" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
                  {resolvedTheme === "dark" ? <SunIcon /> : <MoonIcon />}
                </IconButton>
              </Tooltip>
              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  <button aria-label="Account" style={{ background: "none", border: 0, padding: 0, cursor: "pointer" }}>
                    <Flex align="center" gap="2">
                      <Avatar size="2" fallback={initials(me.name)} radius="full" color="ruby" variant="soft" />
                      <Box display={{ initial: "none", sm: "block" }} style={{ textAlign: "left" }}>
                        <Text as="div" size="2" weight="medium">{me.name}</Text>
                        <Text as="div" size="1" color="gray">{me.title}</Text>
                      </Box>
                    </Flex>
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end">
                  <DropdownMenu.Label>Switch persona</DropdownMenu.Label>
                  {PERSONAS.map((p) => (
                    <DropdownMenu.Item
                      key={p.userId}
                      disabled={p.userId === me.userId}
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
            </Flex>
          </Flex>
        </Container>
      </Box>
      <Container size="4" px="4" py="6">
        {children}
      </Container>
    </Box>
  );
}
