"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ROLES, humanize, type Role } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { inputClass } from "./ui";

const LINKS = [
  { href: "/", label: "Cases" },
  { href: "/ask", label: "Ask" },
  { href: "/steward", label: "Steward" },
];

export function Nav() {
  const path = usePathname();
  const { me, setMe } = useIdentity();
  const active = (href: string) => (href === "/" ? path === "/" || path.startsWith("/cases") : path.startsWith(href));
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-panel/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          Kept
        </Link>
        <nav className="flex gap-1">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              aria-current={active(l.href) ? "page" : undefined}
              className={`rounded-md px-3 py-1.5 text-sm ${active(l.href) ? "bg-soft font-medium text-ink" : "text-muted hover:text-ink"}`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <span className="hidden text-muted sm:inline">Signed in as</span>
          <input
            aria-label="User ID"
            className={`${inputClass} w-28 py-1`}
            value={me.userId}
            onChange={(e) => setMe({ ...me, userId: e.target.value })}
          />
          <select
            aria-label="Role"
            className={`${inputClass} py-1`}
            value={me.role}
            onChange={(e) => setMe({ ...me, role: e.target.value as Role })}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {humanize(r)}
              </option>
            ))}
          </select>
        </div>
      </div>
    </header>
  );
}
