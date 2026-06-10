'use client';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import './workspace.css';

export default function Login() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError('');
    const form = new FormData(e.currentTarget);
    const r = await fetch('/frontend-api/session/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: form.get('email'), password: form.get('password') }),
    });
    if (r.ok) {
      router.push('/workspace');
    } else {
      const data = await r.json().catch(() => ({}));
      setError(data.detail || 'Invalid email or password');
      setLoading(false);
    }
  }

  return (
    <div className="ws-body ws-auth-page">
      <div className="ws-auth-glow-1" />
      <div className="ws-auth-glow-2" />

      <div style={{ width: '100%', maxWidth: 400, position: 'relative', zIndex: 1 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 28, fontWeight: 900, letterSpacing: '-.03em', color: '#fff', marginBottom: 4 }}>
            Atlas <span style={{ color: 'var(--accent)' }}>KB</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Sign in to your workspace</div>
        </div>

        <div className="ws-card" style={{ padding: '32px 28px' }}>
          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div>
              <label className="ws-label">Email</label>
              <input className="ws-input" name="email" type="email" placeholder="you@example.com" required autoFocus />
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label className="ws-label" style={{ margin: 0 }}>Password</label>
                <a href="/forgot-password" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none', fontWeight: 500 }}>
                  Forgot password?
                </a>
              </div>
              <input className="ws-input" name="password" type="password" placeholder="••••••••" required />
            </div>

            {error && (
              <div style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, fontSize: 13, color: 'var(--red)' }}>
                {error}
              </div>
            )}

            <button className="ws-btn ws-btn-primary" type="submit" disabled={loading}
              style={{ width: '100%', marginTop: 4, opacity: loading ? 0.7 : 1 }}>
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: 20, fontSize: 13, color: 'var(--text-dim)' }}>
          No account?{' '}
          <a href="/signup" style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}>
            Create workspace
          </a>
        </p>
      </div>
    </div>
  );
}
