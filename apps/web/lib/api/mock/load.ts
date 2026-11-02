// Load the active pack's sample data through the web server (app/api/sample/[file]/route.ts).
// A pack without sample data yields empty content, so every mock surface shows an explained empty state.

import type { ConsoleFile, ScenarioFile } from "../provisional";

export const EMPTY_CONSOLE: ConsoleFile = {
  pack: { name: "", display_name: "" },
  pack_roles: [],
  identities: [],
  conversations: [],
  datasets: [],
  review_items: [],
  documents: [],
  feedback: [],
  eval_reports: [],
  runs: [],
  traces: {},
  audit: [],
  costs: [],
  users: [],
};
export const EMPTY_SCENARIOS: ScenarioFile = { suggestions: [], scenarios: [] };

export type SampleStatus = "ok" | "missing";

export type SampleData = { console: ConsoleFile; scenarios: ScenarioFile; status: SampleStatus };

async function fetchFile<T>(file: "console" | "scenarios", empty: T): Promise<{ value: T; found: boolean }> {
  try {
    const response = await fetch(`/api/sample/${file}`);
    if (!response.ok) return { value: empty, found: false };
    return { value: { ...empty, ...(await response.json()) }, found: true };
  } catch {
    return { value: empty, found: false };
  }
}

/** Both sample files, fetched once per loader. */
export function sampleLoader(): () => Promise<SampleData> {
  let pending: Promise<SampleData> | null = null;
  return () => {
    pending ??= Promise.all([fetchFile("console", EMPTY_CONSOLE), fetchFile("scenarios", EMPTY_SCENARIOS)]).then(
      ([consoleFile, scenarios]) => ({
        console: structuredClone(consoleFile.value),
        scenarios: scenarios.value,
        status: consoleFile.found && scenarios.found ? "ok" : "missing",
      }),
    );
    return pending;
  };
}
