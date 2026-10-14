"use client";

import { ArrowRightIcon } from "@radix-ui/react-icons";
import {
  Avatar,
  Box,
  Card,
  Container,
  Flex,
  Grid,
  Heading,
  Text,
} from "@radix-ui/themes";
import { motion } from "motion/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";
import { Wordmark, initials } from "@/components/bits";
import { Rise, Stagger } from "@/components/motion";
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
  return (
    <div className="k-frame k-solo">
      <Container size="3" px="4" py="9">
        <Stagger>
          <Rise>
            <Wordmark />
          </Rise>
          <Rise>
            <Heading
              size="9"
              mt="6"
              style={{ maxWidth: 720, lineHeight: 1.05 }}
            >
              Promises customers can keep.
            </Heading>
          </Rise>
          <Rise>
            <Text as="p" size="4" color="gray" mt="4" style={{ maxWidth: 620 }}>
              A guarded next best action for collections: payday-dated, within
              spare cash, explained, and never sent without a person releasing
              it.
            </Text>
          </Rise>
          <Rise>
            <Text as="p" size="2" weight="medium" color="gray" mt="7" mb="3">
              Sign in as
            </Text>
          </Rise>
          <Grid columns={{ initial: "1", sm: "2", md: "3" }} gap="3">
            {PERSONAS.map((p) => (
              <Rise key={p.userId}>
                <motion.div
                  whileHover={{ y: -3 }}
                  whileTap={{ scale: 0.98 }}
                  transition={{ type: "spring", stiffness: 400, damping: 25 }}
                >
                  <Card
                    asChild
                    size="2"
                    style={{ cursor: "pointer", height: "100%" }}
                  >
                    <button
                      onClick={() => {
                        signIn(p);
                        router.push(p.home);
                      }}
                      style={{ textAlign: "left", width: "100%" }}
                    >
                      <Flex gap="3" align="start">
                        <Avatar
                          fallback={initials(p.name)}
                          radius="full"
                          color="ruby"
                          variant="soft"
                        />
                        <Box flexGrow="1">
                          <Flex justify="between" align="center">
                            <Text weight="bold">{p.name}</Text>
                            <ArrowRightIcon color="var(--gray-9)" />
                          </Flex>
                          <Text as="div" size="2" color="ruby" weight="medium">
                            {p.title}
                          </Text>
                          <Text as="p" size="2" color="gray" mt="1">
                            {p.blurb}
                          </Text>
                        </Box>
                      </Flex>
                    </button>
                  </Card>
                </motion.div>
              </Rise>
            ))}
          </Grid>
          <Rise>
            <Text as="p" size="1" color="gray" mt="6">
              Demo personas stand in for single sign-on. Every screen applies
              the same role rules the API enforces.
            </Text>
          </Rise>
        </Stagger>
      </Container>
    </div>
  );
}
