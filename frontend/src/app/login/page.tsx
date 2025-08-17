'use client'

import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabaseClients'
import LoginView from '@/components/login/LoginView'
import DatabaseView from '@/components/database/DatabaseView'

export default function LoginPage() {
  const [session, setSession] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Check current session
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })

    // Listen for auth changes
    const { data: listener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setSession(session)
      }
    )

    return () => {
      listener.subscription.unsubscribe()
    }
  }, [])

  if (loading) return <p className="text-center mt-20">Loading...</p>

  return session ? <DatabaseView /> : <LoginView onLogin={setSession} />
}
