import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/auth-provider";

export const metadata: Metadata = {
  title: "流程自动审批",
  description: "输入项目编号，核对查重、业主与场站类型分类。",
  icons: { icon: "/favicon.png" },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
