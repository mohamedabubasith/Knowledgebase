'use client';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import '../workspace.css';

export default function Signup() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError('');
    const form = new FormData(e.currentTarget);

    const r = await fetch('/frontend-api/session/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        full_name:  form.get('full_name'),
        email:      form.get('email'),
        password:   form.get('password'),
        org_name:   form.get('org_name'),
      }),
    });

    if (r.ok) {
      router.push('/workspace');
    } else {
      const data = await r.json().catch(() => ({}));
      setError(data.detail || 'Signup failed. Please try again.');
      setLoading(false);
    }
  }

  return (
    <div className="ws-body ws-auth-page">
      <div className="ws-auth-glow-1" />
      <div className="ws-auth-glow-2" />

      <div style={{ width: '100%', maxWidth: 440, position: 'relative', zIndex: 1 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 28, fontWeight: 900, letterSpacing: '-.03em', color: '#fff', marginBottom: 4 }}>
            Atlas <span style={{ color: 'var(--accent)' }}>KB</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Create your workspace</div>
        </div>

        <div className="ws-card" style={{ padding: '32px 28px' }}>
          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <label className="ws-label">Full name</label>
              <input className="ws-input" name="full_name" type="text" placeholder="Jane Smith" required autoFocus />
            </div>
            <div>
              <label className="ws-label">Work email</label>
              <input className="ws-input" name="email" type="email" placeholder="you@company.com" required />
            </div>
            <div>
              <label className="ws-label">Password</label>
              <input className="ws-input" name="password" type="password" placeholder="Min 8 characters" required minLength={8} />
            </div>

            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16, marginTop: 2 }}>
              <label className="ws-label">Workspace name</label>
              <input className="ws-input" name="org_name" type="text" placeholder="Acme Corp" required />
              <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
                This becomes your tenant workspace. You can rename it later.
              </p>
            </div>

            {error && (
              <div style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, fontSize: 13, color: 'var(--red)' }}>
                {error}
              </div>
            )}

            <button className="ws-btn ws-btn-primary" type="submit" disabled={loading}
              style={{ width: '100%', marginTop: 4, opacity: loading ? 0.7 : 1 }}>
              {loading ? 'Creating workspace…' : 'Create workspace'}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: 20, fontSize: 13, color: 'var(--text-dim)' }}>
          Already have an account?{' '}
          <a href="/" style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}>
            Sign in
          </a>
        </p>
      </div>
    </div>
  );
}
