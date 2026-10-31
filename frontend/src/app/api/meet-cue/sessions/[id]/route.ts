import type { NextRequest } from "next/server";
import { forwardForSession } from "@/lib/meet-cue/proxy";

/** Current status of a demo session the visitor created in this browser. */
export async function GET(request: NextRequest, ctx: RouteContext<"/api/meet-cue/sessions/[id]">) {
  const { id } = await ctx.params;
  return forwardForSession(request, id, "GET");
}
