"use client";

import { ACTION_LABEL, humanize, money, pct, when, type NBACard } from "@/lib/api";
import { ReviewPanel } from "./review-panel";
import { Banner, Panel, TierBadge } from "./ui";

export function NbaCard({ card }: { card: NBACard }) {
  const p = card.proposal;
  const maxPts = Math.max(1, ...card.reasons.map((r) => r.contribution_pts));
  const wait = card.probabilities.find((a) => a.action === "wait");

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="grid content-start gap-4">
        {card.hard_stop?.blocked && (
          <Banner tone="bad">
            <strong className="font-semibold">Hard stop.</strong> {card.hard_stop.rule_card}
          </Banner>
        )}
        {card.hardship_banner && <Banner tone="warn">{card.hardship_banner}</Banner>}

        <Panel>
          <div className="flex flex-wrap items-center gap-3">
            {p ? <TierBadge tier={p.tier} /> : <span className="text-xs font-semibold text-muted uppercase">No action</span>}
            {p?.is_legacy_strategy && (
              <span className="rounded-full bg-soft px-2.5 py-0.5 text-xs text-muted">Old strategy</span>
            )}
          </div>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight">{card.headline}</h1>
          {p ? (
            <p className="mt-1 text-sm text-muted">
              {ACTION_LABEL[p.action]}
              {p.window_start && ` · ${when(p.window_start)} to ${when(p.window_end)} your time`}
              {` · approve by ${when(p.expires_at)}`}
            </p>
          ) : (
            card.no_action_reason &&
            !card.hard_stop?.blocked && <p className="mt-2 text-sm text-muted">{card.no_action_reason}</p>
          )}
          {p?.sizing && (
            <div className="mt-4 rounded-lg bg-soft p-4">
              <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
                <Stat label={p.sizing.installments > 1 ? "Per payment" : "Promise"} value={money(p.sizing.amount)} />
                {p.sizing.installments > 1 && <Stat label="Payments" value={String(p.sizing.installments)} />}
                <Stat label="First due" value={new Date(p.sizing.due_date).toLocaleDateString("en-CA", { month: "short", day: "numeric" })} />
                <Stat label="Spare cash / period" value={`~${money(p.sizing.spare_cash_estimate)}`} />
              </div>
              {card.sizing_text && <p className="mt-2 text-sm text-muted">{card.sizing_text}</p>}
            </div>
          )}
        </Panel>

        {card.reasons.length > 0 && (
          <Panel title="Why this action">
            <ul className="grid gap-3">
              {card.reasons.map((r) => (
                <li key={r.feature} className="grid gap-1">
                  <div className="flex justify-between gap-4 text-sm">
                    <span>{r.sentence}</span>
                    <span className="shrink-0 font-mono text-xs text-muted">+{r.contribution_pts.toFixed(1)} pts</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-soft">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${(r.contribution_pts / maxPts) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {card.probabilities.length > 0 && (
          <Panel title="Chance of a payment within 14 days">
            <ul className="grid gap-2">
              {card.probabilities.map((a, i) => (
                <li key={a.action} className="grid grid-cols-[10rem_1fr_3rem] items-center gap-3 text-sm">
                  <span className={i === 0 ? "font-medium" : "text-muted"}>{ACTION_LABEL[a.action]}</span>
                  <div className="relative h-2.5 rounded-full bg-soft">
                    <div
                      className={`h-full rounded-full ${i === 0 ? "bg-accent" : "bg-muted/40"}`}
                      style={{ width: pct(a.p_paid_14d) }}
                    />
                    {wait && a.action !== "wait" && (
                      <div
                        className="absolute top-[-3px] h-[16px] w-px bg-ink/60"
                        style={{ left: pct(wait.p_paid_14d) }}
                        title={`Doing nothing: ${pct(wait.p_paid_14d)}`}
                      />
                    )}
                  </div>
                  <span className="text-right font-mono text-xs">{pct(a.p_paid_14d)}</span>
                </li>
              ))}
            </ul>
            {wait && <p className="mt-3 text-xs text-muted">The tick marks the chance if we do nothing ({pct(wait.p_paid_14d)}).</p>}
          </Panel>
        )}
        {card.similar_cases_text && <p className="text-sm text-muted">{card.similar_cases_text}</p>}
      </div>

      <div className="grid content-start gap-4">
        {card.checks.length > 0 && (
          <Panel title="Safety checks">
            <ul className="grid gap-2 text-sm">
              {card.checks.map((c) => (
                <li key={c.check} className="flex gap-2">
                  <span aria-hidden className={c.passed ? "text-good" : "text-bad"}>
                    {c.passed ? "✓" : "✗"}
                  </span>
                  <span>
                    <span className="font-medium capitalize">{humanize(c.check)}</span>
                    <span className="text-muted"> · {c.detail}</span>
                    <span className="sr-only">{c.passed ? "passed" : "failed"}</span>
                  </span>
                </li>
              ))}
            </ul>
          </Panel>
        )}
        {p && <ReviewPanel proposal={p} actions={card.probabilities.map((a) => a.action)} />}
        <Panel title="Provenance">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-muted">Customer</dt>
            <dd className="font-mono">{card.golden_customer_id}</dd>
            <dt className="text-muted">Model</dt>
            <dd className="font-mono">{card.model_version}</dd>
            <dt className="text-muted">Features as of</dt>
            <dd>{when(card.features_as_of)}</dd>
            {p && (
              <>
                <dt className="text-muted">Proposal</dt>
                <dd className="font-mono break-all">{p.proposal_id}</dd>
              </>
            )}
          </dl>
        </Panel>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
