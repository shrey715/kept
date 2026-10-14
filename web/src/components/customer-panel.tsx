"use client";

import { CheckIcon, ClockIcon, EnvelopeClosedIcon, GlobeIcon, LockClosedIcon, MobileIcon, Cross2Icon } from "@radix-ui/react-icons";
import { motion } from "motion/react";
import { humanize, money, type Customer } from "@/lib/api";
import { initials } from "./bits";
import { Donut, spring } from "./motion";

export const SYSTEM_COLOR = { crm: "ruby", card: "iris", loan: "cyan", deposit: "grass", collections: "amber", bureau: "gray" } as const;
/** The studio tint each source system wears in the panel. */
export const SYSTEM_TINT: Record<string, string> = { crm: "rose", card: "lilac", loan: "ice", deposit: "mint", collections: "butter", bureau: "" };
const CHANNELS = ["call", "sms", "email", "push"] as const;
const CHANNEL_LABEL: Record<(typeof CHANNELS)[number], string> = { call: "Call", sms: "SMS", email: "Email", push: "Push" };

/** The golden customer behind a case: who they are, where the record came from, what they owe, and how they may be
 * contacted. Personal data arrives already masked for every role but compliance. */
export function CustomerPanel({ c }: { c: Customer }) {
  const conf = c.match_confidence_min ?? null;
  const name = c.display_name ?? "Unknown customer";
  const hours = c.permitted_call_start_local && c.permitted_call_end_local ? `${c.permitted_call_start_local.slice(0, 5)}–${c.permitted_call_end_local.slice(0, 5)}` : null;
  const payday = c.expected_next_payroll_date
    ? `${new Date(`${c.expected_next_payroll_date}T00:00:00`).toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" })}${c.payroll_frequency_detected ? ` · ${humanize(c.payroll_frequency_detected)}` : ""}`
    : "Not known";
  return (
    <div className="k-cust">
      <div className="k-cust-head">
        <span className="k-cust-ava t-ice" aria-hidden>
          {initials(name)}
        </span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="k-cust-name">{name}</div>
          <div className="k-cust-id">
            <code>{c.golden_customer_id}</code>
            <span className="k-cust-chip" data-tone={c.match_review_status === "auto" ? "good" : "warn"}>
              {c.match_review_status === "auto" ? "Auto-matched" : humanize(c.match_review_status)}
            </span>
          </div>
        </div>
        {conf !== null && (
          <div className="k-cust-match" title="The weakest pairwise match in this customer's cluster">
            <Donut value={conf} size={44} label={`Match confidence ${Math.round(conf * 100)}%`} />
            <span>
              <b className="tabular">{Math.round(conf * 100)}%</b>
              match
            </span>
          </div>
        )}
      </div>

      <div className="k-cust-stats">
        <div>
          <span>Overdue</span>
          <b className="tabular">{money(c.total_overdue, true)}</b>
        </div>
        <div>
          <span>Days past due</span>
          <b className="tabular">{c.max_dpd}</b>
        </div>
        <div>
          <span>Bucket</span>
          <b className="tabular">{c.current_bucket}</b>
        </div>
      </div>

      <section>
        <h4 className="k-cust-h">Source records · {c.source_keys.length} systems</h4>
        <div className="k-cust-sources">
          {c.source_keys.map((k, i) => (
            <motion.div
              key={`${k.system}-${k.key}`}
              className={`k-cust-src ${SYSTEM_TINT[k.system] ? `t-${SYSTEM_TINT[k.system]}` : ""}`}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring, delay: i * 0.05 }}
            >
              <span className="sys">{k.system === "crm" ? "CRM" : k.system[0].toUpperCase() + k.system.slice(1)}</span>
              <code>{k.key}</code>
            </motion.div>
          ))}
        </div>
      </section>

      <section>
        <h4 className="k-cust-h">Contact</h4>
        <dl className="k-cust-rows">
          <div>
            <dt>
              <MobileIcon /> Phone
            </dt>
            <dd className="tabular">{c.primary_phone_e164 ?? "—"}</dd>
          </div>
          <div>
            <dt>
              <EnvelopeClosedIcon /> Email
            </dt>
            <dd>{c.email ?? "—"}</dd>
          </div>
          {hours && (
            <div>
              <dt>
                <ClockIcon /> Calling hours
              </dt>
              <dd className="tabular">
                {hours} local{c.sunday_contact_permitted ? "" : " · not Sundays"}
              </dd>
            </div>
          )}
          {(c.preferred_language || c.province_code) && (
            <div>
              <dt>
                <GlobeIcon /> Language · province
              </dt>
              <dd>{[c.preferred_language && humanize(c.preferred_language), c.province_code].filter(Boolean).join(" · ")}</dd>
            </div>
          )}
        </dl>
        <div className="k-cust-consent" aria-label="Contact consent">
          {CHANNELS.map((ch) => {
            const ok = c.contact_permissions[ch] && !c.do_not_contact;
            return (
              <span key={ch} data-ok={ok}>
                {ok ? <CheckIcon /> : <Cross2Icon />}
                {CHANNEL_LABEL[ch]}
              </span>
            );
          })}
        </div>
      </section>

      <section>
        <h4 className="k-cust-h">Status</h4>
        <dl className="k-cust-rows">
          <div>
            <dt>Hardship</dt>
            <dd>
              <span className="k-cust-chip" data-tone={c.hardship_status === "none" ? "quiet" : "warn"}>
                {c.hardship_status === "none" ? "None recorded" : humanize(c.hardship_status)}
              </span>
            </dd>
          </div>
          <div>
            <dt>Next payday</dt>
            <dd>{payday}</dd>
          </div>
          {c.do_not_contact && (
            <div>
              <dt>Contact</dt>
              <dd>
                <span className="k-cust-chip" data-tone="bad">
                  Do not contact
                </span>
              </dd>
            </div>
          )}
        </dl>
      </section>

      <p className="k-cust-foot">
        <LockClosedIcon /> Personal data is masked for all roles except compliance.
      </p>
    </div>
  );
}
