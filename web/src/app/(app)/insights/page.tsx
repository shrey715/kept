"use client";

import { GlobeIcon } from "@radix-ui/react-icons";
import { Box, Callout, Flex, Skeleton, Text } from "@radix-ui/themes";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { CallingHoursMap, DistrictMap, StressMapView, UpliftExplorer } from "@/components/insight-maps";
import { Rise, Stagger } from "@/components/motion";
import { PageHeader, SectionTitle } from "@/components/page-header";
import { api, type CallingHours, type CollectionsMap, type StressMap, type UpliftLandscape } from "@/lib/api";
import { can, useSession } from "@/lib/session";

// three.js loads on the client only, after the page has drawn
const SceneSkeleton = () => <Skeleton height="460px" style={{ borderRadius: 18 }} />;
const CollectionsTowers = dynamic(() => import("@/components/insight-scenes").then((m) => m.CollectionsTowers), { ssr: false, loading: SceneSkeleton });
const UpliftSurface = dynamic(() => import("@/components/insight-scenes").then((m) => m.UpliftSurface), { ssr: false, loading: SceneSkeleton });

type Who = NonNullable<ReturnType<typeof useSession>["me"]>;

function useInsight<T>(me: Who | null, get: (w: Who) => Promise<T>) {
  const [state, setState] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    if (!me) return;
    let live = true;
    get(me).then(
      (data) => live && setState({ data }),
      (e: Error) => live && setState({ error: e.message }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.userId, me?.role]);
  return state;
}

export default function InsightsPage() {
  const { me } = useSession();
  const allowed = !!me && can.portfolio(me.role);
  const hours = useInsight<CallingHours>(allowed ? me : null, api.callingHours);
  const stress = useInsight<StressMap>(allowed ? me : null, api.stressMap);
  const towers = useInsight<CollectionsMap>(allowed ? me : null, api.collectionsMap);
  const uplift = useInsight<UpliftLandscape>(allowed ? me : null, api.upliftLandscape);
  if (!me) return null;
  if (!allowed)
    return (
      <Text as="p" size="2" color="gray">
        Insights are for analysts, hardship specialists, team leads and compliance.
      </Text>
    );

  return (
    <Stagger>
      <Rise>
        <PageHeader
          icon={<GlobeIcon />}
          eyebrow="Insights"
          title="Portfolio maps"
          sub="Calling hours, financial stress and overdue balances by place, and where a call changes the outcome. Every area and point is a group of at least 50 customers."
        />
      </Rise>

      <Section eyebrow="Compliance" title="Calling hours right now" state={hours} height={520}>
        {(d) => <CallingHoursMap data={d} />}
      </Section>

      <Section eyebrow="Early hardship" title="Financial stress by province" state={stress} height={520}>
        {(d) => (
          <>
            <StressMapView data={d} />
            <Text as="p" size="1" color="gray" mt="3">
              The first month has no earlier month to compare, so cash flow and payroll are blank there.
            </Text>
          </>
        )}
      </Section>

      <Section
        eyebrow="Collections map"
        title="Overdue balance by postal district"
        state={towers}
        height={520}
      >
        {(d) => <DistrictMap data={d} towers={(m) => <CollectionsTowers data={d} mode={m} />} />}
      </Section>

      <Section eyebrow="Uplift model" title="Where a call helps" state={uplift} height={520}>
        {(d) => (
          <>
            <UpliftExplorer data={d} surface={<UpliftSurface data={d} />} />
            <Text as="p" size="1" color="gray" mt="3">
              The live uplift model ({d.model_version}), with every other input at tonight&apos;s median. Each dot is a group of 50 or more of tonight&apos;s {d.cases.toLocaleString("en-CA")} cases, coloured by the card&apos;s action.
            </Text>
          </>
        )}
      </Section>
    </Stagger>
  );
}

function Section<T>({
  eyebrow,
  title,
  state,
  height,
  aside,
  children,
}: {
  eyebrow: string;
  title: string;
  state: { data?: T; error?: string };
  height: number;
  aside?: React.ReactNode;
  children: (d: T) => React.ReactNode;
}) {
  return (
    <Rise>
      <Box mt="5">
        <div className="k-card" style={{ padding: 22 }}>
          <Flex justify="between" align="start" gap="3" wrap="wrap">
            <SectionTitle eyebrow={eyebrow} title={title} />
            {aside}
          </Flex>
          {state.error ? (
            <Callout.Root color="gray">
              <Callout.Text>Not available: {state.error}</Callout.Text>
            </Callout.Root>
          ) : state.data ? (
            children(state.data)
          ) : (
            <Skeleton height={`${height}px`} style={{ borderRadius: 18 }} />
          )}
        </div>
      </Box>
    </Rise>
  );
}
