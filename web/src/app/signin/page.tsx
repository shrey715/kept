"use client";

import { ArrowRightIcon, LockClosedIcon } from "@radix-ui/react-icons";
import { Avatar, Box, Flex, Text, Tooltip } from "@radix-ui/themes";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";
import { Wordmark, initials } from "@/components/bits";
import { Rise, Stagger } from "@/components/motion";
import { PencilSketch } from "@/components/pencil-sketch";
import { PERSONAS, useSession } from "@/lib/session";

export default function SignInPage() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}

/** `/signin?as=agent-7&next=/queue` signs straight in: one link per persona for presenters. */
function SignIn() {
  const { signIn } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const done = useRef(false);
  useEffect(() => {
    const p = PERSONAS.find((x) => x.userId === params.get("as"));
    if (!p || done.current) return;
    done.current = true;
    signIn(p);
    const next = params.get("next");
    router.replace(next?.startsWith("/") ? next : p.home);
  }, [params, signIn, router]);
  const go = (p: (typeof PERSONAS)[number]) => {
    signIn(p);
    router.push(p.home);
  };
  return (
    <div className="k-signin">
      <section className="k-signin-art" aria-hidden={false}>
        <Link href="/" aria-label="Kept home" style={{ color: "inherit", textDecoration: "none" }}>
          <Wordmark />
        </Link>
        <div className="k-signin-sketch">
          <PencilSketch />
        </div>
        <Box>
          <h2 className="k-display" style={{ maxWidth: 460 }}>
            Promises customers can keep.
          </h2>
          <Text as="p" size="3" color="gray" mt="3" style={{ maxWidth: 440 }}>
            Dated the day after payday, sized to spare cash, explained, and never sent without a person releasing it.
          </Text>
        </Box>
      </section>

      <section className="k-signin-form">
        <Stagger style={{ width: "100%", maxWidth: 440 }}>
          <Rise>
            <div className="k-eyebrow">Kept workspace</div>
            <h1 className="k-display" style={{ fontSize: 40 }}>
              Welcome back
            </h1>
            <Text as="p" size="2" color="gray" mt="2">
              Sign in to see your queue, approvals and the evidence behind every card.
            </Text>
          </Rise>
          <Rise>
            <Tooltip content="Production signs in through the bank's identity provider. This demo uses the accounts below.">
              <button className="k-sso" disabled aria-disabled>
                <LockClosedIcon /> Continue with bank single sign-on
              </button>
            </Tooltip>
          </Rise>
          <Rise>
            <div className="k-or">
              <span>or use a demo account</span>
            </div>
          </Rise>
          <div className="k-accounts" role="list">
            {PERSONAS.map((p) => (
              <Rise key={p.userId}>
                <motion.button
                  role="listitem"
                  className="k-account"
                  onClick={() => go(p)}
                  whileHover={{ x: 3 }}
                  whileTap={{ scale: 0.99 }}
                  transition={{ type: "spring", stiffness: 420, damping: 28 }}
                >
                  <Avatar size="3" fallback={initials(p.name)} radius="full" color="ruby" variant="soft" />
                  <Box style={{ minWidth: 0, flex: 1, textAlign: "left" }}>
                    <Flex align="baseline" gap="2">
                      <Text size="2" weight="medium">
                        {p.name}
                      </Text>
                      <Text size="1" style={{ color: "var(--k-red)" }} weight="medium">
                        {p.title}
                      </Text>
                    </Flex>
                    <Text as="div" size="1" color="gray" truncate>
                      {p.blurb}
                    </Text>
                  </Box>
                  <ArrowRightIcon className="k-account-arrow" />
                </motion.button>
              </Rise>
            ))}
          </div>
          <Rise>
            <Text as="p" size="1" color="gray" mt="5">
              Synthetic data. Every screen applies the same role rules the API enforces.
            </Text>
          </Rise>
        </Stagger>
      </section>
    </div>
  );
}
