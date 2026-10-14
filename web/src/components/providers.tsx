"use client";

import { Theme } from "@radix-ui/themes";
import { MotionConfig } from "motion/react";
import { ThemeProvider } from "next-themes";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <Theme accentColor="ruby" grayColor="sand" radius="full" panelBackground="solid" className="app-root">
        <MotionConfig reducedMotion="user">{children}</MotionConfig>
      </Theme>
    </ThemeProvider>
  );
}
