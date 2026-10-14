"use client";

import { ViewTransition } from "react";

// Re-mounts on every navigation: the browser fades the old page up and out and the new one in (globals.css).
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransition enter="k-page-in" exit="k-page-out" default="none">
      <div>{children}</div>
    </ViewTransition>
  );
}
