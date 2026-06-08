'use client';
import { FormEvent, useState } from 'react';
import '../workspace.css';

export default function ForgotPassword() {
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError('');
    const form = new FormData(e.currentTarget);
    const r = await fetch('/frontend-api/backend/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: form.get('email') }),
    });
    setLoading(false);
    if (r.ok || r.status === 204) {
      setSent(true);
    } else {
      setError('Something went wrong. Please try again.');
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
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Reset your password</div>
        </div>

        <div className="ws-card" style={{ padding: '32px 28px' }}>
          {sent ? (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 36, marginBottom: 16 }}>✉️</div>
              <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text)', marginBottom: 8 }}>Check your email</div>
              <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                If that email is registered, we sent a password reset link. Check your inbox.
              </p>
              <a href="/" style={{ display: 'inline-block', marginTop: 20, fontSize: 13, color: 'var(--accent)', fontWeight: 600, textDecoration: 'none' }}>
                ← Back to sign in
              </a>
            </div>
          ) : (
            <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0, lineHeight: 1.6 }}>
                Enter your email and we'll send a reset link if the account exists.
              </p>
              <div>
                <label className="ws-label">Email</label>
                <input className="ws-input" name="email" type="email" placeholder="you@example.com" required autoFocus />
              </div>
              {error && (
                <div style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, fontSize: 13, color: 'var(--red)' }}>
                  {error}
                </div>
              )}
              <button className="ws-btn ws-btn-primary" type="submit" disabled={loading}
                style={{ width: '100%', opacity: loading ? 0.7 : 1 }}>
                {loading ? 'Sending…' : 'Send reset link'}
              </button>
              <a href="/" style={{ textAlign: 'center', fontSize: 13, color: 'var(--text-dim)', textDecoration: 'none' }}>
                ← Back to sign in
              </a>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
