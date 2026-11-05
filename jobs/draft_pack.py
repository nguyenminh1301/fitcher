"""Draft Domain Pack items for review from the pack's profile and documents (DECISIONS §11 step 4).

Run with ``docker compose run --rm jobs python -m jobs.draft_pack --pack <name> --allow-billable``.
It reads ``build/packs/<pack>/profile.json`` (``jobs.profile``) and the
pack's live ``kb_docs`` chunks (``jobs.ingest_docs`` or the Documents page),
or only one document's chunks with ``--document <id>``, and drafts
``datasets.yaml``, ``glossary.yaml``, ``metrics.yaml`` and ``examples.yaml``
in that order (``--files`` picks some) with one ``sql-gen`` call per file.
Drafts are written into ``packs/<pack>/`` with ``status: draft`` and never
replace an approved item; review them in the console's Review section.

Every call is billable: without ``--allow-billable`` the job prints the
prompt size per file and exits 2 without calling the model.
"""

import argparse
from pathlib import Path
import sys

from clickhouse_connect.driver.exceptions import Error as ClickHouseError

from app.config import SettingsError, load_settings
from app.data.clickhouse import ClientWarehouse
from app.llm.client import LiteLLMClient, LLMError
from app.llm.tiers import TierMap
from app.observability.tracing import trusted_pack_calls
from app.onboarding.documents import live_chunks
from app.onboarding.drafter import DRAFT_FILES, Drafter, DraftError, draft_files
from app.onboarding.pack_yaml import PackFiles
from app.onboarding.profiler import read_profile
from app.packs.loader import PackValidationError
from app.search.client import QdrantSearch, SearchError
from jobs.lib.clickhouse import admin_client

ROOT = Path(__file__).resolve().parents[1]
# A rough characters-per-token ratio for the printed estimate.
CHARS_PER_TOKEN = 4


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path, default=ROOT / "packs")
    parser.add_argument("--files", nargs="+", choices=DRAFT_FILES, default=list(DRAFT_FILES))
    parser.add_argument("--document", help="draft from this document's chunks only")
    parser.add_argument("--allow-billable", action="store_true", help="send the billable sql-gen calls")
    return parser.parse_args(argv)


def read_chunks(search: QdrantSearch, pack: str, document_id: str | None) -> list[dict]:
    try:
        return live_chunks(search, pack, document_id)
    except SearchError:
        # A pack with no kb_docs alias yet has no document to draft from.
        return []


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings()
        compiled_dir = Path(settings.compiled_pack_dir)
        profile = read_profile(compiled_dir, args.pack)
        chunks = read_chunks(QdrantSearch(settings.qdrant_url), args.pack, args.document)
        files = PackFiles(args.packs_dir / args.pack)
        llm = LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key, tiers=TierMap(settings.model_tiers))
        drafter = Drafter(llm, ClientWarehouse(admin_client()))
        print(f"Pack {args.pack}: profile {'found' if profile else 'missing'}, {len(chunks)} document chunks")
        if not args.allow_billable:
            for file, characters in drafter.estimate(files, profile, chunks).items():
                if file in args.files:
                    print(f"  {file}: about {characters // CHARS_PER_TOKEN} prompt tokens")
            print("Drafting is billable; run again with --allow-billable to send these calls.")
            return 2
        with trusted_pack_calls():
            results = draft_files(drafter, files, profile, chunks, args.files)
    except (DraftError, LLMError, PackValidationError, SettingsError, ClickHouseError, SearchError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    for file, result in results.items():
        print(f"  {file}: {len(result.added)} added, {len(result.updated)} updated, "
              f"{len(result.skipped_approved)} approved left unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
