import type { Metadata } from "next";
import { Geist_Mono, Inter, Inter_Tight, Kalam, Source_Serif_4 } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const sans = Inter({ variable: "--font-sans", subsets: ["latin"] });
const display = Inter_Tight({ variable: "--font-display", subsets: ["latin"], weight: ["300", "400", "500", "600"] });
const hand = Kalam({ variable: "--font-hand", subsets: ["latin"], weight: ["300", "400"] });
const mono = Geist_Mono({ variable: "--font-mono", subsets: ["latin"] });
const serif = Source_Serif_4({ variable: "--font-serif", subsets: ["latin"], weight: ["500", "600", "700"] });

export const metadata: Metadata = {
  title: "Kept",
  description: "Guarded next best action for promises customers can keep",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${hand.variable} ${mono.variable} ${serif.variable}`} suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
