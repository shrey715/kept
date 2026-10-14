"use client";

import { CheckIcon, CopyIcon } from "@radix-ui/react-icons";
import { useState } from "react";

const KEYWORDS =
  /\b(select|from|where|and|or|not|group by|order by|having|limit|offset|join|left join|inner join|on|as|with|case|when|then|else|end|in|is|null|desc|asc|nulls last|count|sum|avg|min|max|filter|coalesce|distinct|between|interval|date_trunc|strftime|quarter|union all|over|partition by)\b/gi;
const BREAK_BEFORE = /\s+(from|where|group by|order by|having|limit|left join|inner join|join|union all)\s+/gi;

/** Line breaks before each clause, so a query reads top to bottom. ponytail: a regex, not a parser. */
export function formatSql(sql: string): string {
  return sql
    .replace(/\s+/g, " ")
    .replace(BREAK_BEFORE, (_, kw: string) => `\n${kw} `)
    .replace(/,\s*(?![^()]*\))/g, ",\n       ")
    .trim();
}

/** A query, formatted and lightly highlighted (keywords, strings, numbers), with a copy button. */
export function SqlBlock({ sql, label = "SQL" }: { sql: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const text = formatSql(sql);
  const parts = text.split(/('[^']*'|\b\d+(?:\.\d+)?\b)/g);
  return (
    <div className="k-sql">
      <div className="k-sql-head">
        <span>{label}</span>
        <button
          className="k-text-btn"
          onClick={() => {
            void navigator.clipboard.writeText(text).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1400);
            });
          }}
          aria-label="Copy the query"
        >
          {copied ? <CheckIcon /> : <CopyIcon />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        {parts.map((p, i) =>
          /^'/.test(p) ? (
            <span key={i} className="k-sql-str">
              {p}
            </span>
          ) : /^\d/.test(p) ? (
            <span key={i} className="k-sql-num">
              {p}
            </span>
          ) : (
            p.split(KEYWORDS).map((w, j) =>
              j % 2 ? (
                <span key={`${i}-${j}`} className="k-sql-kw">
                  {w}
                </span>
              ) : (
                w
              ),
            )
          ),
        )}
      </pre>
    </div>
  );
}
