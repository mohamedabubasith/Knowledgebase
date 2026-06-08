import { NextResponse } from 'next/server';

export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete('kb_access');
  response.cookies.delete('kb_refresh');
  return response;
}
