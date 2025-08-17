// app/layout.tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import ReactQueryProvider from "./providers/ReactQueryProvider";
import { AuthProvider } from "@/context/AuthContext";
import ClientShell from "./providers/ClientShell"; // ✅ client wrapper that hides sidebar on /login

export const metadata: Metadata = {
  title: "CurricAlign",
  description: "Curriculum alignment and job matching platform",
};

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <ReactQueryProvider>
          <AuthProvider>
            {/* ClientShell handles Sidebar visibility and layout spacing */}
            <ClientShell>{children}</ClientShell>
          </AuthProvider>
        </ReactQueryProvider>
      </body>
    </html>
  );
}
