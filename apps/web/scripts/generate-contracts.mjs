// Turn the backend contract JSON Schemas in lib/contracts/schemas into TypeScript (DECISIONS §7).
// Run with `npm run contracts:generate` after scripts/generate_contract_types.py; a test fails on drift.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

const BANNER = "// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.";

/** The TypeScript module for one contract schema. */
export async function contractSource(schema, name) {
  return compile(schema, name, {
    bannerComment: BANNER,
    additionalProperties: false,
    style: { singleQuote: false, semi: true, printWidth: 120 },
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const contracts = join(dirname(fileURLToPath(import.meta.url)), "..", "lib", "contracts");
  const names = readdirSync(join(contracts, "schemas"))
    .filter((file) => file.endsWith(".schema.json"))
    .map((file) => file.replace(".schema.json", ""));
  for (const name of names) {
    const schema = JSON.parse(readFileSync(join(contracts, "schemas", `${name}.schema.json`), "utf-8"));
    writeFileSync(join(contracts, `${name}.ts`), await contractSource(schema, name));
  }
}
