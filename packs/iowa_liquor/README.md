# iowa_liquor

The Domain Pack of the second industry (DECISIONS §4): every spirits purchase by a Class E liquor licensee in Iowa in 2025, from the `liquor_sales` mart (one row per invoice line).

Data: Iowa Liquor Sales, 2025 (Iowa Data Hub dataset 1262), published by the Iowa Department of Revenue, Alcohol Operations Bureau, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
It is served from the fixture PostgreSQL and copied into ClickHouse through `jobs/sources/iowa_liquor.yaml`; see [infra/sources/iowa_liquor](../../infra/sources/iowa_liquor/README.md).

The pack was onboarded with the Phase 10 pipeline only:

- `datasets.yaml`, `metrics.yaml`, `glossary.yaml` and `examples.yaml` were drafted by `jobs.draft_pack` from the mart profile and approved in the console's Review section; the reviewer's corrections are listed in [the eval report](../../docs/eval/iowa_liquor-report.md).
- `business_profile.yaml`, `policies.yaml` and `relationships.yaml` were written by the company, as access rules and conventions are its decisions: `analyst` reads everything, `polk_county_manager` reads only Polk County's lines, and `vendor_partner` never sees the state's bottle cost or margin.
- `eval.yaml` and `sample_data/` are hand-written; the sample data is invented and never copied from the dataset.
