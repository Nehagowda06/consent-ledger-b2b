import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Consent Ledger",
  description: "B2B consent management and compliance center",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
