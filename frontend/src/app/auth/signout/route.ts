// app/auth/signout/route.ts
import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { createRouteHandlerClient } from '@supabase/auth-helpers-nextjs';

export const runtime = 'nodejs';

export async function POST(request: Request) {
  const supabase = createRouteHandlerClient({ cookies });

  await supabase.auth.signOut();

  // Optional: support ?next=/somewhere
  const url = new URL(request.url);
  const next = url.searchParams.get('next') || '/login';
  return NextResponse.redirect(new URL(next, url.origin));
}
