// app/logout/page.tsx
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { createServerComponentClient } from '@supabase/auth-helpers-nextjs';
import LogoutView from '@/components/logout/LogoutView';

export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default async function LogoutPage() {
  const supabase = createServerComponentClient({
    cookies: async () => cookies(), // ✅ async getter
  });

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    redirect('/login');
  }

  return <LogoutView />;
}
