import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const body = await request.json();
  const result = await fetch(`${process.env.BACKEND_URL}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await result.json();
  if (!result.ok) return NextResponse.json(data, { status: result.status });

  const response = NextResponse.json({ ok: true, tenant_id: data.tenant_id });
  const secure = process.env.NODE_ENV === 'production';
  response.cookies.set('kb_access',  data.access_token,  { httpOnly: true, sameSite: 'lax', secure, maxAge: 1800,   path: '/' });
  response.cookies.set('kb_refresh', data.refresh_token, { httpOnly: true, sameSite: 'lax', secure, maxAge: 604800, path: '/' });
  return response;
}
