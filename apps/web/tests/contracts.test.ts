import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { contractSource } from "../scripts/generate-contracts.mjs";

const CONTRACTS = join(__dirname, "..", "lib", "contracts");
const schemas = readdirSync(join(CONTRACTS, "schemas")).filter((file) => file.endsWith(".schema.json"));

describe("generated contract types", () => {
  it("covers the backend contracts", () => {
    expect(schemas.sort()).toEqual([
      "ask_event.schema.json", "ask_request.schema.json", "audit_row.schema.json", "chart_spec.schema.json",
      "conversation.schema.json", "conversation_group.schema.json", "conversation_patch.schema.json", "conversation_thread.schema.json",
      "cost_row.schema.json", "dataset_view.schema.json", "document_list.schema.json", "document_roles_change.schema.json",
      "document_view.schema.json", "draft_result.schema.json", "eval_report_view.schema.json", "eval_run_started.schema.json",
      "feedback_input.schema.json", "feedback_row.schema.json", "group_input.schema.json", "model_tier_change.schema.json",
      "model_tiers.schema.json", "proposal_result.schema.json", "query_spec.schema.json", "result.schema.json",
      "review_item.schema.json", "review_item_patch.schema.json", "run_row.schema.json", "run_trace.schema.json",
      "user_roles.schema.json", "user_view.schema.json",
    ]);
  });

  for (const file of schemas) {
    it(`${file} matches its committed TypeScript`, async () => {
      const name = file.replace(".schema.json", "");
      const schema = JSON.parse(readFileSync(join(CONTRACTS, "schemas", file), "utf-8"));

      expect(await contractSource(schema, name)).toBe(readFileSync(join(CONTRACTS, `${name}.ts`), "utf-8"));
    });
  }
});
