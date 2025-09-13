// lib/supabase/server.ts
import { cookies } from 'next/headers';
import { createServerClient } from '@supabase/ssr';

/**
 * For Server Components/Pages (e.g., app/login/page.tsx, app/logout/page.tsx)
 * Next 15 returns ReadonlyRequestCookies -> read only (no .set()).
 * We provide get + no-op set/remove to satisfy @supabase/ssr.
 */
export async function createServerSupabase() {
  const requestCookies = await cookies(); // must await in Next 15

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return requestCookies.get(name)?.value;
        },
        set(_name: string, _value: string, _options?: unknown) {
          /* no-op in Server Components */
        },
        remove(_name: string, _options?: unknown) {
          /* no-op in Server Components */
        },
      } as any,
    }
  );
}
