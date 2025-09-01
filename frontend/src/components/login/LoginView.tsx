'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';
import type { Session } from '@supabase/supabase-js';

interface LoginViewProps {
  onLogin?: (session: Session) => void;
}

export default function LoginView({ onLogin }: LoginViewProps) {
  const supabase = createClientComponentClient();
  const router = useRouter();

  // form state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  // UX messages
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (error) throw error;

      if (data.session) {
        onLogin?.(data.session);
        router.push('/dashboard');
      } else {
        setError('No session returned. Please try again.');
      }
    } catch (e: any) {
      setError(e?.message ?? 'Failed to log in.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6 sm:px-8 py-12 bg-[var(--background)]">
      <div className="btn_border_silver rounded-xl shadow-md w-full max-w-md">
        <div className="card_background rounded-xl p-8">
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

          {/* Title */}
          <h1 className="text-2xl font-bold text_defaultColor text-center mb-6">
            Welcome Back!
          </h1>

          {/* Error */}
          {error && (
            <p className="mb-4 rounded px-3 py-2 text-sm text-center bg-red-50 text-red-700 border border-red-200">
              {error}
            </p>
          )}

          {/* Form */}
          <form onSubmit={handleLogin} className="space-y-5">
            <div>
              <label className="block text-sm text_secondaryColor mb-1">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-teal)]"
                required
              />
            </div>

            <div>
              <label className="block text-sm text_secondaryColor mb-1">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-teal)]"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn_background_purple font-medium py-2.5 transition disabled:opacity-60 w-full"
            >
              {loading ? 'Logging in…' : 'Login'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
