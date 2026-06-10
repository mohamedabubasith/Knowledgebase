'use client';
import { FormEvent, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import '../workspace.css';

function ResetForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get('token') ?? '';
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError('');
    const form = new FormData(e.currentTarget);
    const password = form.get('password') as string;
    const confirm  = form.get('confirm') as string;
    if (password !== confirm) { setError('Passwords do not match'); setLoading(false); return; }

    const r = await fetch('/frontend-api/backend/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: password }),
    });
    setLoading(false);
    if (r.ok || r.status === 204) {
      router.push('/?reset=1');
    } else {
      const data = await r.json().catch(() => ({}));
      setError(data.detail || 'Invalid or expired token.');
    }
  }

  if (!token) return (
    <div style={{ textAlign: 'center', color: 'var(--red)', padding: 24 }}>
      Invalid reset link. <a href="/forgot-password" style={{ color: 'var(--accent)' }}>Request a new one →</a>
    </div>
  );

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <label className="ws-label">New password</label>
        <input className="ws-input" name="password" type="password" placeholder="Min 8 characters" required minLength={8} autoFocus />
      </div>
      <div>
        <label className="ws-label">Confirm password</label>
        <input className="ws-input" name="confirm" type="password" placeholder="Repeat password" required minLength={8} />
      </div>
      {error && (
        <div style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, fontSize: 13, color: 'var(--red)' }}>
          {error}
        </div>
      )}
      <button className="ws-btn ws-btn-primary" type="submit" disabled={loading}
        style={{ width: '100%', opacity: loading ? 0.7 : 1 }}>
        {loading ? 'Updating…' : 'Set new password'}
      </button>
    </form>
  );
}

export default function ResetPassword() {
  return (
    <div className="ws-body ws-auth-page">
      <div className="ws-auth-glow-1" />
      <div className="ws-auth-glow-2" />
      <div style={{ width: '100%', maxWidth: 400, position: 'relative', zIndex: 1 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 28, fontWeight: 900, letterSpacing: '-.03em', color: '#fff', marginBottom: 4 }}>
            Atlas <span style={{ color: 'var(--accent)' }}>KB</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Set a new password</div>
        </div>
        <div className="ws-card" style={{ padding: '32px 28px' }}>
          <Suspense fallback={<div style={{ color: 'var(--text-dim)', fontSize: 13 }}>Loading…</div>}>
            <ResetForm />
          </Suspense>
        </div>
        <a href="/" style={{ display: 'block', textAlign: 'center', marginTop: 20, fontSize: 13, color: 'var(--text-dim)', textDecoration: 'none' }}>
          ← Back to sign in
        </a>
      </div>
    </div>
  );
}
