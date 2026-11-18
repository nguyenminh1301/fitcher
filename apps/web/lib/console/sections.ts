// The console's pages in navigation order (DECISIONS §15). fitcher is a personal app, so the owner sees every
// page; the groups follow what a page is about: the data, its quality, what happened, and the settings.

import type { Feature } from "@/lib/api/client";

export type SectionGroup = "data" | "quality" | "activity" | "settings";

export type Section = {
  key: string;
  /** No group for the Overview, which sits above the groups. */
  group: SectionGroup | null;
  path: string;
  icon: string;
  /** The api feature the section reads, which decides its Sample data badge. */
  feature: Feature | null;
};

export const SECTIONS: Section[] = [
  { key: "overview", group: null, path: "/console", icon: "home", feature: null },
  { key: "sources", group: "data", path: "/console/sources", icon: "database", feature: "sources" },
  { key: "datasets", group: "data", path: "/console/datasets", icon: "table", feature: "datasets" },
  { key: "documents", group: "data", path: "/console/documents", icon: "fileText", feature: "documents" },
  { key: "review", group: "quality", path: "/console/review", icon: "clipboardCheck", feature: "review" },
  { key: "feedback", group: "quality", path: "/console/feedback", icon: "thumbsUp", feature: "feedbackReview" },
  { key: "evaluation", group: "quality", path: "/console/evaluation", icon: "gauge", feature: "evaluation" },
  { key: "runs", group: "activity", path: "/console/runs", icon: "activity", feature: "runs" },
  { key: "costs", group: "activity", path: "/console/costs", icon: "coins", feature: "costs" },
  { key: "audit", group: "activity", path: "/console/audit", icon: "shieldCheck", feature: "audit" },
  { key: "models", group: "settings", path: "/console/models", icon: "cpu", feature: "models" },
  { key: "security", group: "settings", path: "/console/security", icon: "lock", feature: "owner" },
];

export const GROUPS: SectionGroup[] = ["data", "quality", "activity", "settings"];

/** The section key of a console path such as ``/console/runs/abc``; ``/console`` itself is the Overview. */
export function sectionOf(pathname: string): string {
  const match = /^\/console\/([^/]+)/.exec(pathname);
  return match ? match[1] : "overview";
}
