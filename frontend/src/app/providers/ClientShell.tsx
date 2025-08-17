// app/providers/ClientShell.tsx
'use client';

import { usePathname } from "next/navigation";
import Sidebar from "@/components/dashboard/Sidebar";

export default function ClientShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname?.startsWith("/login");

  return (
    <>
      {!isLogin && <Sidebar />}
      <main className={!isLogin ? "ml-16 min-h-screen transition-all duration-300" : "min-h-screen"}>
        {children}
      </main>
    </>
  );
}
