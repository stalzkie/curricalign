import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Sidebar from "../components/dashboard/Sidebar";
import ReactQueryProvider from "./providers/ReactQueryProvider"; // ✅ Add this

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CurricAlign",
  description: "Curriculum alignment and job matching platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {/* Wrap entire app in React Query Provider */}
        <ReactQueryProvider>
          <Sidebar />
          <main className="ml-16 min-h-screen transition-all duration-300">
            {children}
          </main>
        </ReactQueryProvider>
      </body>
    </html>
  );
}
