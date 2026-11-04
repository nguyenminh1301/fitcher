"""Write the LiteLLM configuration from the gateway settings and the catalog, then start the proxy.

``config.yaml`` holds the settings shared by every model; each file of
``catalog/`` holds the aliases of one provider and the environment variables
they need (``requires``). A block whose variables are not all set is left out,
so an alias without its key is never loaded and LiteLLM starts without it
(DECISIONS §2 Model tiers). The merged file is written to ``OUTPUT`` and the
image's entrypoint is started with it; the arguments of this script are passed
on. Only the standard library and PyYAML, both in the LiteLLM image, are used.
"""

from collections.abc import Mapping
import os
from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent
OUTPUT = Path("/tmp/litellm-config.yaml")
ENTRYPOINT = "docker/prod_entrypoint.sh"


def build(base: dict, blocks: list[dict], env: Mapping[str, str]) -> tuple[dict, list[str]]:
    """The configuration with the model list of every block whose variables are set, and the aliases loaded."""
    models = []
    for block in blocks:
        if all(env.get(name) for name in block.get("requires", [])):
            models.extend(block.get("model_list", []))
    return {**base, "model_list": models}, [model["model_name"] for model in models]


def load_blocks(directory: Path) -> list[dict]:
    return [yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.yaml"))]


def main(argv: list[str]) -> None:
    base = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    config, aliases = build(base, load_blocks(HERE / "catalog"), os.environ)
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(f"LiteLLM catalog aliases: {', '.join(aliases) or 'none'}", file=sys.stderr, flush=True)
    os.execv(ENTRYPOINT, [ENTRYPOINT, "--config", str(OUTPUT), *argv])


if __name__ == "__main__":
    main(sys.argv[1:])
