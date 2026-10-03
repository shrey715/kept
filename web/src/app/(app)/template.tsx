"use client";

import { motion } from "motion/react";

// Re-mounts on every navigation: each page slides up into place.
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 30 }}
    >
      {children}
    </motion.div>
  );
}
