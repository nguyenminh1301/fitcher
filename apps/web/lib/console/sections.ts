// The workspace console's sections and which console role opens each (DECISIONS §15). The api
// enforces the same rule on every endpoint; this list only decides what the navigation shows.

import type { Feature } from "@/lib/api/client";

export type SectionGroup = "knowledge" | "observe" | "quality" | "administration";

export type Section = {
  key: string;
  group: SectionGroup;
  path: string;
  icon: string;
  roles: string[];
  /** The api feature the section reads, which decides its Sample data badge. */
  feature: Feature;
  /** Shown only in team mode: individual mode has one owner and no accounts. */
  teamOnly?: boolean;
};

const REVIEWER = "pack_reviewer";
const ADMIN = "admin";

/** In navigation order; groups appear in this order too. */
export const SECTIONS: Section[] = [
  { key: "review", group: "knowledge", path: "/console/review", icon: "clipboardCheck", roles: [REVIEWER], feature: "review" },
  { key: "documents", group: "knowledge", path: "/console/documents", icon: "fileText", roles: [REVIEWER], feature: "documents" },
  { key: "datasets", group: "knowledge", path: "/console/datasets", icon: "table", roles: [REVIEWER], feature: "datasets" },
  { key: "feedback", group: "knowledge", path: "/console/feedback", icon: "thumbsUp", roles: [REVIEWER], feature: "feedbackReview" },
  { key: "runs", group: "observe", path: "/console/runs", icon: "activity", roles: [ADMIN], feature: "runs" },
  { key: "audit", group: "observe", path: "/console/audit", icon: "shieldCheck", roles: [ADMIN], feature: "audit" },
  { key: "costs", group: "observe", path: "/console/costs", icon: "coins", roles: [ADMIN], feature: "costs" },
  { key: "evaluation", group: "quality", path: "/console/evaluation", icon: "gauge", roles: [REVIEWER, ADMIN], feature: "evaluation" },
  { key: "users", group: "administration", path: "/console/users", icon: "users", roles: [ADMIN], feature: "users", teamOnly: true },
  { key: "sources", group: "administration", path: "/console/sources", icon: "database", roles: [ADMIN], feature: "sources" },
  { key: "models", group: "administration", path: "/console/models", icon: "compass", roles: [ADMIN], feature: "models" },
];

/** The sections these roles may open, in navigation order; empty for a role without console access. */
export function allowedSections(roles: string[], mode?: "individual" | "team"): Section[] {
  return SECTIONS.filter((section) => section.roles.some((role) => roles.includes(role))
    && !(section.teamOnly && mode === "individual"));
}

/** The section key of a console path such as ``/console/runs/abc``, or null for ``/console``. */
export function sectionOf(pathname: string): string | null {
  const match = /^\/console\/([^/]+)/.exec(pathname);
  return match ? match[1] : null;
}
