// The console's pages (DECISIONS §15). fitcher is a personal app with one owner, so the sidebar keeps six areas
// and a page that belongs with another one is a tab of that area: Datasets beside Sources; Feedback and
// Evaluation beside Review under Quality; Query log and Costs beside Runs under Activity; Models and Security
// under Settings. Every page keeps its own path, so links to it still work.

import type { Feature } from "@/lib/api/client";

export type Section = {
  key: string;
  path: string;
  icon: string;
  /** The api feature the section reads, which decides its Sample data badge. */
  feature: Feature | null;
};

export type Area = {
  key: string;
  icon: string;
  /** The pages of the area in tab order; the first one is where the sidebar link goes. */
  pages: string[];
};

export const SECTIONS: Section[] = [
  { key: "overview", path: "/console", icon: "home", feature: null },
  { key: "sources", path: "/console/sources", icon: "database", feature: "sources" },
  { key: "datasets", path: "/console/datasets", icon: "table", feature: "datasets" },
  { key: "documents", path: "/console/documents", icon: "fileText", feature: "documents" },
  { key: "review", path: "/console/review", icon: "clipboardCheck", feature: "review" },
  { key: "feedback", path: "/console/feedback", icon: "thumbsUp", feature: "feedbackReview" },
  { key: "evaluation", path: "/console/evaluation", icon: "gauge", feature: "evaluation" },
  { key: "runs", path: "/console/runs", icon: "activity", feature: "runs" },
  { key: "audit", path: "/console/audit", icon: "shieldCheck", feature: "audit" },
  { key: "costs", path: "/console/costs", icon: "coins", feature: "costs" },
  { key: "models", path: "/console/models", icon: "cpu", feature: "models" },
  { key: "security", path: "/console/security", icon: "lock", feature: "owner" },
];

export const AREAS: Area[] = [
  { key: "overview", icon: "home", pages: ["overview"] },
  { key: "sources", icon: "database", pages: ["sources", "datasets"] },
  { key: "documents", icon: "fileText", pages: ["documents"] },
  { key: "quality", icon: "clipboardCheck", pages: ["review", "feedback", "evaluation"] },
  { key: "activity", icon: "activity", pages: ["runs", "audit", "costs"] },
  { key: "settings", icon: "wrench", pages: ["models", "security"] },
];

export function sectionPath(key: string): string {
  return SECTIONS.find((section) => section.key === key)?.path ?? "/console";
}

/** The area a page belongs to. */
export function areaOf(section: string): Area {
  return AREAS.find((area) => area.pages.includes(section)) ?? AREAS[0];
}

/** The section key of a console path such as ``/console/runs/abc``; ``/console`` itself is the Overview. */
export function sectionOf(pathname: string): string {
  const match = /^\/console\/([^/]+)/.exec(pathname);
  return match ? match[1] : "overview";
}
