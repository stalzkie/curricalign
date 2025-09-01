'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';
import type { User, Session } from '@supabase/supabase-js';

interface AccountViewProps {
  initialUser: User | null;
  initialSession: Session | null;
}

export default function AccountView({ initialUser, initialSession }: AccountViewProps) {
  const supabase = useMemo(() => createClientComponentClient(), []);
  const router = useRouter();

  // Seed from server props; reconcile with client session on mount.
  const [user, setUser] = useState<User | null>(initialUser ?? initialSession?.user ?? null);
  const [redirecting, setRedirecting] = useState(false);

  // Displayed info
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');

  // Form state
  const [newDisplayName, setNewDisplayName] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);

  // Password state
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [updatingPassword, setUpdatingPassword] = useState(false);

  // UX
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Hydrate summary fields whenever user changes
  useEffect(() => {
    if (!user) return;
    setEmail(user.email ?? '');
    const m = user.user_metadata ?? {};
    const name = m.full_name ?? m.name ?? m.display_name ?? '';
    setDisplayName(name);
    setNewDisplayName(name); // prefill editor
  }, [user]);

  // Reconcile with client-side session on mount and watch auth changes
  useEffect(() => {
    let alive = true;

    (async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (!alive) return;

      if (!session) {
        // Server thought we had a session but client doesn't → send to login
        if (user) {
          setRedirecting(true);
          router.replace('/login');
        }
        return;
      }

      // Pull a fresh user (ensures latest metadata after any redirects)
      const { data: { user: freshUser } } = await supabase.auth.getUser();
      if (!alive) return;
      if (freshUser) setUser(freshUser);
    })();

    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      if (!session) {
        setRedirecting(true);
        router.replace('/login');
      } else {
        setUser(session.user);
      }
    });

    return () => {
      alive = false;
      sub.subscription.unsubscribe();
    };
  }, [supabase, router]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update display name (stored in user_metadata.full_name)
  const onSaveProfile = async () => {
    setErr(null); setMsg(null);
    if (!user) return;

    if ((newDisplayName || '') === (displayName || '')) {
      setMsg('No changes to save.');
      return;
    }

    try {
      setSavingProfile(true);
      const { data, error } = await supabase.auth.updateUser({
        data: { full_name: newDisplayName || null },
      });
      if (error) throw error;

      // refresh displayed info with returned user
      if (data.user) setUser(data.user);
      setMsg('Display name updated.');
    } catch (e: any) {
      setErr(e?.message ?? 'Failed to update profile.');
    } finally {
      setSavingProfile(false);
    }
  };

  // Change password
  const onUpdatePassword = async () => {
    setErr(null); setMsg(null);

    if (!newPassword) return setErr('Please enter a new password.');
    if (newPassword !== confirmPassword) return setErr('Passwords do not match.');
    if (newPassword.length < 8) return setErr('Password must be at least 8 characters.');

    try {
      setUpdatingPassword(true);
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw error;

      setMsg('Password updated.');
      setNewPassword(''); setConfirmPassword('');
    } catch (e: any) {
      setErr(e?.message ?? 'Failed to update password.');
    } finally {
      setUpdatingPassword(false);
    }
  };

  if (redirecting) {
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <p className="text-gray-600">Redirecting to login…</p>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">Account Settings</h1>
        <p className="text-lg text-gray-600 mb-6">
          Manage your account preferences and profile information
        </p>

        {(msg || err) && (
          <div
            className={`mb-6 rounded-lg border p-4 ${
              err ? 'border-red-200 bg-red-50 text-red-700' : 'border-green-200 bg-green-50 text-green-700'
            }`}
            role="status"
          >
            {err ?? msg}
          </div>
        )}

        {/* Read-only summary */}
        <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 mb-8">
          <h2 className="text-2xl font-semibold text-gray-800 mb-4">Your Account</h2>
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <dt className="text-sm text-gray-500">Display Name</dt>
              <dd className="mt-1 text-base text-gray-900">{displayName || '—'}</dd>
            </div>
            <div>
              <dt className="text-sm text-gray-500">Email</dt>
              <dd className="mt-1 text-base text-gray-900">{email || '—'}</dd>
            </div>
          </dl>
        </div>

        {/* Update display name */}
        <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 mb-8">
          <h2 className="text-2xl font-semibold text-gray-800 mb-4">Update Display Name</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                New Display Name
              </label>
              <input
                type="text"
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
                disabled={savingProfile}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
                placeholder="Enter a new display name"
              />
            </div>
          </div>
          <button
            onClick={onSaveProfile}
            disabled={savingProfile}
            className="mt-4 px-4 py-2 bg-green-700 text-white rounded-md hover:bg-green-600 transition-colors disabled:opacity-60"
          >
            {savingProfile ? 'Saving…' : 'Save Changes'}
          </button>
        </div>

        {/* Change password */}
        <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
          <h2 className="text-2xl font-semibold text-gray-800 mb-4">Change Password</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">New Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={updatingPassword}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
                placeholder="Enter new password"
                autoComplete="new-password"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Confirm Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={updatingPassword}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
                placeholder="Re-enter new password"
                autoComplete="new-password"
              />
            </div>
          </div>
          <button
            onClick={onUpdatePassword}
            disabled={updatingPassword}
            className="mt-4 px-4 py-2 bg-green-700 text-white rounded-md hover:bg-green-600 transition-colors disabled:opacity-60"
          >
            {updatingPassword ? 'Updating…' : 'Update Password'}
          </button>
          <p className="text-xs text-gray-5ß00 mt-3">
            Password updates require that you are currently signed in. If your session expired, sign in again.
          </p>
        </div>
      </div>
    </div>
  );
}
