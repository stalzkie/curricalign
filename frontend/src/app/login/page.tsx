// app/login/page.tsx
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { createServerComponentClient } from '@supabase/auth-helpers-nextjs';
import LoginView from '@/components/login/LoginView';

export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default async function LoginPage() {
  // ✅ Provide an async getter so Next 15's "await cookies()" rule is satisfied
  const supabase = createServerComponentClient({
    cookies: async () => cookies(),
  });

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (session) {
    redirect('/dashboard');
  }

  return <LoginView />;
}
