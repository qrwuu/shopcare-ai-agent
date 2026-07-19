import type { Metadata } from "next";
import { Playfair_Display, DM_Sans, IBM_Plex_Mono } from "next/font/google";
import NavBar from "@/components/NavBar";
import "./globals.css";

const displayFont = Playfair_Display({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-display",
});

const bodyFont = DM_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  variable: "--font-body",
});

const monoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "店小服 ShopCare",
  description: "电商售后决策与人工审核协同助手",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        suppressHydrationWarning
        className={`${displayFont.variable} ${bodyFont.variable} ${monoFont.variable} h-screen flex flex-col bg-background-base font-body`}
      >
        <NavBar />
        <div className="flex flex-col flex-1 overflow-hidden">
          {children}
        </div>
      </body>
    </html>
  );
}
