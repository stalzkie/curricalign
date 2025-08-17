// app/dashboard/page.tsx
'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import Dashboard from '@/components/dashboard/Dashboard';

export default function DashboardPage() {
  const { session, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !session) {
      router.replace('/login'); // ✅ not logged in → go to login
    }
  }, [loading, session, router]);

  if (loading || !session) return null; // or a spinner/skeleton

  return <Dashboard />; // ✅ Sidebar shows because route isn't /login
}
