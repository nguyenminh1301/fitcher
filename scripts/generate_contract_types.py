"""Write the JSON Schemas of the backend contracts the web app uses (DECISIONS §7).

Run with ``uv run --project apps/api python scripts/generate_contract_types.py``,
then ``npm --prefix apps/web run contracts:generate`` to turn the schemas into
TypeScript under ``apps/web/lib/contracts/``. Tests on both sides fail while a
committed schema or type differs from what these produce.
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.contracts.query_spec import QuerySpec  # noqa: E402 - needs apps/api on the path
from app.contracts.result import Result  # noqa: E402

CONTRACTS = {"query_spec": QuerySpec, "result": Result}
SCHEMAS = ROOT / "apps" / "web" / "lib" / "contracts" / "schemas"


def main() -> int:
    SCHEMAS.mkdir(parents=True, exist_ok=True)
    for name, model in CONTRACTS.items():
        text = json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
        (SCHEMAS / f"{name}.schema.json").write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {name}.schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
