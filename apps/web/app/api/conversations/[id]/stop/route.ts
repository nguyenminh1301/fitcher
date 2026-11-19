// Stop the question a conversation is answering; leaving the chat page does not stop it (app/api/live_runs.py).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/conversations/${encodeURIComponent(id)}/stop`);
}
