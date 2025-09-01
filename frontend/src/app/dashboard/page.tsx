// app/dashboard/page.tsx
import Dashboard from '@/components/dashboard/Dashboard';

export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default function DashboardPage() {
  // Auth is enforced by middleware; if not signed in, it will redirect to /login
  return <Dashboard />;
}
