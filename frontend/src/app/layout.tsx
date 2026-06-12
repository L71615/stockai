import type { Metadata } from "next";
import "./globals.css";
import { AppLayout } from "@/components/app-layout";

export const metadata: Metadata = {
  title: "StockAI — A-share Investment Review & AI Coaching",
  description:
    "A-share investment review and AI coaching platform. Record trades, track holdings, and get AI-driven analysis.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="dark h-full antialiased">
      <body className="min-h-full bg-background text-foreground">
        <AppLayout>{children}</AppLayout>
      </body>
    </html>
  );
}
