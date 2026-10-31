import type { NextRequest } from "next/server";
import { forwardForSession } from "@/lib/meet-cue/proxy";

/** Cancels a scheduled demo session the visitor created in this browser. */
export async function POST(request: NextRequest, ctx: RouteContext<"/api/meet-cue/sessions/[id]/cancel">) {
  const { id } = await ctx.params;
  return forwardForSession(request, id, "POST", "/cancel");
}
