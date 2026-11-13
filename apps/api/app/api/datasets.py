"""GET /datasets: the console's read-only Datasets page (DECISIONS §15).

Lists the compiled pack's datasets with their columns, types, roles and
descriptions, and the pack roles granted each dataset in ``policies.yaml``,
aggregate-only grants included. Only a ``pack_reviewer`` reaches it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.console import require_reviewer
from app.api.runtime import get_compiled
from app.auth.principal import Principal
from app.contracts.review import DatasetColumnView, DatasetView
from app.packs.compiler import CompiledPack
from app.packs.search_indices import PackRoles

router = APIRouter()


@router.get("/datasets")
def list_datasets(
    _: Annotated[Principal, Depends(require_reviewer)],
    compiled: Annotated[CompiledPack, Depends(get_compiled)],
) -> list[DatasetView]:
    roles = PackRoles(compiled.pack)
    return [
        DatasetView(
            id=dataset.id, description=dataset.description, grain=dataset.grain, time_column=dataset.time_column,
            readable_roles=roles.dataset(dataset.id),
            columns=[
                DatasetColumnView(name=column.name, type=column.type, role=column.role, description=column.description)
                for column in dataset.columns
            ],
        )
        for dataset in compiled.pack.datasets.datasets
    ]
