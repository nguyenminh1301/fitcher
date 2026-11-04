"""Write the synthetic widget dataset that every fixture source system serves.

Run with ``python infra/sources/fixtures/generate.py``; the output in
``infra/sources/fixtures/widgets/`` is committed, so seeding never runs this.
The data is invented from a fixed random seed: 40 widgets, 3,000 sales and
300 refunds, with plain values (no commas, quotes or NULLs) so every seed
script can read the CSV files without a CSV library.
"""

import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "widgets"
SEED = 20261105
CATEGORIES = ["gear", "tool", "part", "kit"]
REGIONS = ["north", "south", "east", "west"]
FIRST_DAY = date(2024, 1, 1)
DAYS = 547  # through 2025-06-30
WIDGETS, SALES, REFUNDS = 40, 3000, 300


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def generate() -> dict[str, list[dict[str, str]]]:
    rng = random.Random(SEED)
    widgets = [
        {
            "widget_id": f"W{n:02d}",
            "widget_name": f"Widget {n:02d}",
            "category": CATEGORIES[n % len(CATEGORIES)],
            "list_price": _money(Decimal(rng.randint(500, 9900)) / 100),
        }
        for n in range(1, WIDGETS + 1)
    ]
    sales = []
    for n in range(1, SALES + 1):
        widget = rng.choice(widgets)
        quantity = rng.randint(1, 5)
        discount = Decimal(rng.choice([100, 95, 90, 85])) / 100
        sales.append(
            {
                "sale_id": f"S{n:05d}",
                "sold_on": (FIRST_DAY + timedelta(days=rng.randrange(DAYS))).isoformat(),
                "widget_id": widget["widget_id"],
                "region": rng.choice(REGIONS),
                "quantity": str(quantity),
                "sale_amount": _money(Decimal(widget["list_price"]) * quantity * discount),
            }
        )
    refunds = []
    for n, sale in enumerate(sorted(rng.sample(sales, REFUNDS), key=lambda s: s["sale_id"]), start=1):
        share = Decimal(rng.choice([100, 50, 25])) / 100
        refunds.append(
            {
                "refund_id": f"R{n:04d}",
                "sale_id": sale["sale_id"],
                "refunded_on": (date.fromisoformat(sale["sold_on"]) + timedelta(days=rng.randint(1, 30))).isoformat(),
                "refund_total": _money(Decimal(sale["sale_amount"]) * share),
            }
        )
    return {"widgets": widgets, "sales": sales, "refunds": refunds}


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for name, rows in generate().items():
        with (DATA_DIR / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
