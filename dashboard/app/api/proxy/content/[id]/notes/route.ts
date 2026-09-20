import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Server-only: this route handler is the ONLY place CONTENT_AGENT_API_SECRET is ever
// read. It never reaches the browser bundle (no NEXT_PUBLIC_ prefix).
export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const secret = process.env.CONTENT_AGENT_API_SECRET;
  if (!secret) {
    return NextResponse.json(
      { detail: "CONTENT_AGENT_API_SECRET is not configured on this server." },
      { status: 503 }
    );
  }

  const body = await request.text();
  const upstream = await fetch(`${API_BASE_URL}/api/content/${id}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Secret": secret },
    body,
  });
  const data = await upstream.text();
  return new NextResponse(data, { status: upstream.status, headers: { "Content-Type": "application/json" } });
}
