"""Load a folder of company documents into a pack through the same code path as the Documents page.

Run with ``docker compose run --rm jobs python -m jobs.ingest_docs --pack <name> --folder <dir>``.
The folder holds ``manifest.yaml``:

.. code-block:: yaml

    default_allowed_roles: [analyst]
    documents:
      - file: pricing-handbook.pdf
      - file: returns-policy.docx
        allowed_roles: [analyst, northwest_sales]

Each document is checked, stored, parsed, screened, embedded (billable,
through the ``embed`` tier) and indexed into the pack's ``kb_docs`` exactly as
an upload is. A document already registered for the pack is skipped; the job
exits 1 when any document failed and 2 for a manifest it cannot use.
"""

import argparse
from pathlib import Path
import sys

import yaml

from app.config import load_settings
from app.llm.embeddings import LiteLLMEmbeddings
from app.llm.tiers import EMBED_TIER
from app.onboarding.docs_parser import DocumentRejected
from app.onboarding.documents import ClickHouseDocumentRegistry, DocumentService, DuplicateDocument
from app.screening.screen import Screener
from app.search.client import QdrantSearch
from jobs.lib.clickhouse import admin_client

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "manifest.yaml"


class ManifestError(ValueError):
    """The folder's manifest is missing or malformed."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True)
    parser.add_argument("--folder", required=True, type=Path, help=f"folder with {MANIFEST} and the documents")
    parser.add_argument("--packs-dir", type=Path, default=ROOT / "packs")
    return parser.parse_args(argv)


def read_manifest(folder: Path) -> list[tuple[Path, list[str]]]:
    """``(file, allowed_roles)`` per listed document, in manifest order."""
    path = folder / MANIFEST
    if not path.is_file():
        raise ManifestError(f"{path} does not exist")
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    default = content.get("default_allowed_roles") or []
    entries = []
    for item in content.get("documents") or []:
        if not isinstance(item, dict) or not item.get("file"):
            raise ManifestError(f"every entry of {MANIFEST} needs a file")
        file = folder / item["file"]
        if not file.is_file():
            raise ManifestError(f"{file} does not exist")
        entries.append((file, list(item.get("allowed_roles") or default)))
    if not entries:
        raise ManifestError(f"{MANIFEST} lists no documents")
    return entries


def pack_roles(pack_dir: Path) -> list[str]:
    content = yaml.safe_load((pack_dir / "policies.yaml").read_text(encoding="utf-8")) or {}
    return [role["id"] for role in content.get("roles") or []]


def build_service(pack: str, roles: list[str]) -> DocumentService:
    settings = load_settings()
    return DocumentService(
        pack=pack, pack_roles=roles, registry=ClickHouseDocumentRegistry(admin_client()),
        search=QdrantSearch(settings.qdrant_url),
        embeddings=LiteLLMEmbeddings(
            settings.litellm_base_url, settings.litellm_master_key, settings.embedding_dimensions,
            alias=settings.model_tiers[EMBED_TIER],
        ),
        screener=Screener.from_settings(settings), store_dir=Path(settings.documents_dir),
        compiled_dir=Path(settings.compiled_pack_dir), max_bytes=settings.document_max_bytes,
    )


def ingest(service: DocumentService, entries: list[tuple[Path, list[str]]], uploaded_by: str) -> int:
    failed = 0
    for file, roles in entries:
        try:
            record = service.upload(file.name, file.read_bytes(), roles, uploaded_by)
        except DuplicateDocument as error:
            print(f"  skipped {file.name}: {error}")
            continue
        except Exception as error:  # noqa: BLE001 - one failed document must not stop the others
            failed += 1
            reason = str(error) if isinstance(error, DocumentRejected) else f"{type(error).__name__}: {error}"
            print(f"  failed {file.name}: {reason}")
            continue
        print(f"  indexed {file.name}: {record.chunk_count} chunks, {record.blocked_chunks} blocked by screening")
    return failed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        entries = read_manifest(args.folder)
        roles = pack_roles(args.packs_dir / args.pack)
    except (ManifestError, OSError) as error:
        print(error, file=sys.stderr)
        return 2
    print(f"Ingesting {len(entries)} documents into pack {args.pack}:")
    failed = ingest(build_service(args.pack, roles), entries, uploaded_by="jobs.ingest_docs")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
