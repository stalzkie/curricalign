'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';

type Status = 'idle' | 'signingout' | 'done' | 'error';

export default function LogoutView() {
  const router = useRouter();
  const supabase = createClientComponentClient();
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const ranOnce = useRef(false);

  const doSignOut = useCallback(async () => {
    setStatus('signingout');
    setErrorMsg(null);
    try {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
      setStatus('done');
      // Let middleware refresh cookies on the next navigation
      setTimeout(() => router.replace('/login'), 200);
    } catch (e: any) {
      setStatus('error');
      setErrorMsg(e?.message || 'Failed to sign out.');
    }
  }, [router, supabase]);

  useEffect(() => {
    if (ranOnce.current) return; // prevent double-run in React StrictMode
    ranOnce.current = true;
    void doSignOut();
  }, [doSignOut]);

  return (
    <div className="min-h-screen flex items-center justify-center px-6 sm:px-8 py-12 bg-[var(--background)]">
      <div className="btn_border_silver rounded-xl shadow-md w-full max-w-md">
        <div className="card_background rounded-xl p-8 text-center">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <Image
              src="/logo-wordmark.svg"
              alt="App Logo"
              width={140}
              height={140}
              priority
            />
          </div>

          <h1 className="text-2xl font-bold text_defaultColor mb-2">
            Signing you out
          </h1>

          {status === 'signingout' && (
            <p className="text_secondaryColor">Please wait…</p>
          )}

          {status === 'done' && (
            <p className="text_secondaryColor">
              You’ve been signed out. Redirecting…
            </p>
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
                  onClick={() => void doSignOut()}
                  disabled={status !== 'error'} // ✅ Only clickable if still in "error" state
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
