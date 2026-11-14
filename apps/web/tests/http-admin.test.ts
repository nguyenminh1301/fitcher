import { describe, expect, it, vi } from "vitest";

import {
  createHttpAudit, createHttpCosts, createHttpEvaluation, createHttpFeedbackReview, createHttpRuns, createHttpUsers,
} from "@/lib/api/http/admin";

function fetcher(status = 200, body: unknown = []) {
  return vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return status === 204 ? new Response(null, { status }) : Response.json(body, { status });
  });
}

const calls = (fetch: ReturnType<typeof fetcher>) => fetch.mock.calls.map(([url, init]) => [url, init?.method ?? "GET"]);

describe("http admin sections", () => {
  it("reads runs, a trace, audit rows and costs", async () => {
    const fetch = fetcher(200, []);
    await createHttpRuns(fetch).list();
    await createHttpRuns(fetch).trace("t 1");
    await createHttpAudit(fetch).list();
    await createHttpCosts(fetch).list();
    expect(calls(fetch)).toEqual([
      ["/api/admin/runs", "GET"], ["/api/admin/runs/t%201", "GET"], ["/api/admin/audit", "GET"], ["/api/admin/costs", "GET"],
    ]);
  });

  it("answers null for an unknown trace or report", async () => {
    expect(await createHttpRuns(fetcher(404, { detail: "run not found" })).trace("t9")).toBeNull();
    expect(await createHttpEvaluation(fetcher(404, { detail: "eval report not found" })).report("r9")).toBeNull();
  });

  it("proposes an example from one run and returns the api's answer", async () => {
    const fetch = fetcher(200, { proposed: false, reason: "the run was denied" });
    expect(await createHttpFeedbackReview(fetch).propose("t9")).toEqual({ proposed: false, reason: "the run was denied" });
    expect(calls(fetch)).toEqual([["/api/admin/feedback/t9/proposal", "POST"]]);
  });

  it("starts an eval run and refuses a second with the api's reason", async () => {
    const fetch = fetcher(202, { pack: "shop", running: true });
    expect(await createHttpEvaluation(fetch).start()).toEqual({ pack: "shop", running: true });
    await expect(createHttpEvaluation(fetcher(409, { detail: "an eval run of shop is still running" })).start())
      .rejects.toThrow("409: an eval run of shop is still running");
  });

  it("sets roles and enables or disables a user", async () => {
    const fetch = fetcher(204);
    const users = createHttpUsers(fetch);
    await users.setRoles("u1", ["analyst"]);
    await users.setEnabled("u1", false);
    await users.setEnabled("u1", true);
    expect(calls(fetch)).toEqual([
      ["/api/admin/users/u1", "PATCH"], ["/api/admin/users/u1", "PATCH"], ["/api/admin/users/u1", "PATCH"],
    ]);
    expect(fetch.mock.calls.map(([, init]) => JSON.parse(init?.body as string))).toEqual([
      { roles: ["analyst"] }, { enabled: false }, { enabled: true },
    ]);
  });

  it("creates an account and resets a password through the admin routes", async () => {
    const created = { id: "u9", email: "bea@example.com", display_name: "Bea", roles: ["analyst"], enabled: true };
    const fetch = fetcher(200, created);
    const users = createHttpUsers(fetch);

    expect(await users.create({ email: "bea@example.com", display_name: "Bea", password: "battery staple", roles: ["analyst"] })).toEqual(created);
    await users.resetPassword("u9", "new password");

    expect(calls(fetch)).toEqual([["/api/admin/users", "POST"], ["/api/admin/users/u9/password", "POST"]]);
    expect(JSON.parse(fetch.mock.calls[1][1]?.body as string)).toEqual({ password: "new password" });
  });
});
