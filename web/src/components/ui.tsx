import type { Tier } from "@/lib/api";

export function Panel({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line bg-panel p-5 ${className}`}>
      {title && <h2 className="mb-3 text-xs font-semibold tracking-wider text-muted uppercase">{title}</h2>}
      {children}
    </section>
  );
}

const TIER_STYLE: Record<Tier, string> = {
  green: "bg-good-soft text-good",
  amber: "bg-warn-soft text-warn",
  red: "bg-bad-soft text-bad",
  blocked: "bg-bad-soft text-bad",
};
const TIER_TEXT: Record<Tier, string> = {
  green: "Green · team lead batch",
  amber: "Amber · assigned agent",
  red: "Red · specialist + second person",
  blocked: "Blocked",
};

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${TIER_STYLE[tier]}`}>
      {TIER_TEXT[tier]}
    </span>
  );
}

export function Banner({ tone, children }: { tone: "warn" | "bad" | "info"; children: React.ReactNode }) {
  const style = {
    warn: "border-warn bg-warn-soft",
    bad: "border-bad bg-bad-soft",
    info: "border-accent bg-soft",
  }[tone];
  return <div className={`rounded-lg border-l-4 px-4 py-3 text-sm ${style}`}>{children}</div>;
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const style = {
    primary: "bg-accent text-accent-ink hover:opacity-90",
    ghost: "border border-line text-ink hover:bg-soft",
    danger: "border border-bad text-bad hover:bg-bad-soft",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${style} ${className}`}
    />
  );
}

export const inputClass =
  "rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent";

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-medium text-muted">
      {label}
      {children}
    </label>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-soft ${className}`} />;
}
