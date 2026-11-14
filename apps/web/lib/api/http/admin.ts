// The admin and feedback sections from the api (Phase 12), through the web server's /api/admin routes,
// which add the session's access token. The api answers runs, audit, costs and users only to an admin,
// feedback to a pack_reviewer, and eval reports to either.

import type { PasswordReset, UserChange } from "@/lib/contracts";

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

type Fetcher = typeof fetch;

async function call(fetcher: Fetcher, url: string, init?: RequestInit): Promise<Response> {
  const response = await fetcher(url, init);
  if (!response.ok) throw await refused(response);
  return response;
}

const post = (body: unknown): RequestInit => ({
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
});
const patch = (body: UserChange): RequestInit => ({
  method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
});
const id = (value: string) => encodeURIComponent(value);

export function createHttpRuns(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["runs"] {
  return {
    list: async () => (await call(fetcher, "/api/admin/runs")).json(),
    trace: async (traceId) => {
      const response = await fetcher(`/api/admin/runs/${id(traceId)}`);
      if (response.status === 404) return null;
      if (!response.ok) throw await refused(response);
      return response.json();
    },
  };
}

export function createHttpAudit(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["audit"] {
  return { list: async () => (await call(fetcher, "/api/admin/audit")).json() };
}

export function createHttpCosts(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["costs"] {
  return { list: async () => (await call(fetcher, "/api/admin/costs")).json() };
}

export function createHttpFeedbackReview(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["feedbackReview"] {
  return {
    list: async () => (await call(fetcher, "/api/admin/feedback")).json(),
    propose: async (traceId) => (await call(fetcher, `/api/admin/feedback/${id(traceId)}/proposal`, { method: "POST" })).json(),
  };
}

export function createHttpEvaluation(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["evaluation"] {
  return {
    reports: async () => (await call(fetcher, "/api/admin/eval-reports")).json(),
    report: async (reportId) => {
      const response = await fetcher(`/api/admin/eval-reports/${id(reportId)}`);
      if (response.status === 404) return null;
      if (!response.ok) throw await refused(response);
      return response.json();
    },
    start: async () => (await call(fetcher, "/api/admin/eval-runs", { method: "POST" })).json(),
  };
}

export function createHttpUsers(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["users"] {
  return {
    list: async () => (await call(fetcher, "/api/admin/users")).json(),
    setRoles: async (userId, roles) => {
      await call(fetcher, `/api/admin/users/${id(userId)}`, patch({ roles }));
    },
    setEnabled: async (userId, enabled) => {
      await call(fetcher, `/api/admin/users/${id(userId)}`, patch({ enabled }));
    },
    create: async (user) => (await call(fetcher, "/api/admin/users", post(user))).json(),
    resetPassword: async (userId, password) => {
      await call(fetcher, `/api/admin/users/${id(userId)}/password`, post({ password } satisfies PasswordReset));
    },
  };
}

export const httpRuns = createHttpRuns();
export const httpAudit = createHttpAudit();
export const httpCosts = createHttpCosts();
export const httpFeedbackReview = createHttpFeedbackReview();
export const httpEvaluation = createHttpEvaluation();
export const httpUsers = createHttpUsers();
