import { NextResponse } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Server-only: this route handler is the ONLY place CONTENT_AGENT_API_SECRET is ever
// read. It never reaches the browser bundle (no NEXT_PUBLIC_ prefix). No UI page
// calls this yet (imports are run via the backend CLI/admin path for now) - included
// for completeness/future use.
export async function POST() {
  const secret = process.env.CONTENT_AGENT_API_SECRET;
  if (!secret) {
    return NextResponse.json(
      { detail: "CONTENT_AGENT_API_SECRET is not configured on this server." },
      { status: 503 }
    );
  }

  const upstream = await fetch(`${API_BASE_URL}/api/imports/run`, {
    method: "POST",
    headers: { "X-API-Secret": secret },
  });
  const data = await upstream.text();
  return new NextResponse(data, { status: upstream.status, headers: { "Content-Type": "application/json" } });
}
