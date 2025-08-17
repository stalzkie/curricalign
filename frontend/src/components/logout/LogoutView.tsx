// src/app/components/logout/LogoutView.tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { supabase } from '@/lib/supabaseClients';
import { useQueryClient } from '@tanstack/react-query';

export default function LogoutView() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<'idle' | 'signingout' | 'done' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const ranOnce = useRef(false);

  useEffect(() => {
    if (ranOnce.current) return;
    ranOnce.current = true;

    (async () => {
      setStatus('signingout');

      try {
        // @ts-ignore optional; ignore if unused
        supabase.getChannels?.().forEach((ch: any) => supabase.removeChannel(ch));
      } catch {}

      try {
        queryClient.clear();
      } catch {}

      const { error } = await supabase.auth.signOut();
      if (error) {
        setStatus('error');
        setErrorMsg(error.message || 'Failed to sign out.');
        return;
      }

      try {
        await fetch('/auth/signout', { method: 'POST' }); // clear SSR cookies
      } catch (e) {
        console.warn('Server signout route not reachable:', e);
      }

      setStatus('done');
      setTimeout(() => router.replace('/login'), 400);
    })();
  }, [queryClient, router]);

  return (
    <div className="min-h-screen flex items-center justify-center px-6 sm:px-8 py-12 bg-[var(--background)]">
      <div className="btn_border_silver rounded-xl shadow-md w-full max-w-md">
        <div className="card_background rounded-xl p-8 text-center">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <Image
              src="/logo-wordmark.svg" // match LoginView logo path
              alt="App Logo"
              width={140}
              height={140}
              priority
            />
          </div>

          <h1 className="text-2xl font-bold text_defaultColor mb-2">Signing you out</h1>

          {status === 'signingout' && (
            <p className="text_secondaryColor">Please wait…</p>
          )}

          {status === 'done' && (
            <p className="text_secondaryColor">You’ve been signed out. Redirecting…</p>
          )}

          {status === 'error' && (
            <>
              <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-red-700">
                Error: {errorMsg}
              </p>
              <div className="flex justify-center gap-2">
                <button
                  className="btn_background_purple font-medium py-2.5 w-auto"
                  onClick={() => router.replace('/login')}
                >
                  Go to Login
                </button>
                <button
                  className="rounded border px-3 py-2 hover:bg-gray-50"
                  onClick={() => location.reload()}
                >
                  Try Again
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
