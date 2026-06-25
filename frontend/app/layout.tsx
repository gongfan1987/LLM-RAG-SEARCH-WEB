import type { Metadata } from "next";
import "./globals.css";
import { AppBootstrap } from "@/components/AppBootstrap";

export const metadata: Metadata = {
  title: "AI 对话助手",
  description: "简洁高效的 AI 对话应用",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AppBootstrap />
        {children}
      </body>
    </html>
  );
}
