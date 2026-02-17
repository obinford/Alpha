import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { BankrollProvider } from "@/lib/bankroll-context";

export const metadata: Metadata = {
  title: "RTM Picks",
  description: "AI-powered sports betting intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="flex min-h-screen">
        <BankrollProvider>
          <Sidebar />
          <main className="flex-1 p-8">{children}</main>
        </BankrollProvider>
      </body>
    </html>
  );
}
