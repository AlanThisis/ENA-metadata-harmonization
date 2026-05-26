---
description: Separate ENA samples into disease, control, or other paper-defined groups using ENA metadata, abstracts, disease annotations, and the paper's cohort language.
---

# Separate Samples

Use this skill when the task is to classify ENA sample accessions into disease, control, treatment, responder/non-responder, or any other cohort definition described by a paper or study metadata.

Work in this order:

1. Identify the study accession, paper identifiers, and the exact grouping question.
2. Retrieve sample-level metadata with `scripts/get_ena_project_samples.py`.
3. Retrieve paper context with `scripts/get_abstracts.py` and disease entities with `scripts/get_disease_entities.py` when PMID or PMCID is available.
4. Infer the grouping rule from explicit metadata fields first.
5. If metadata is insufficient, use the paper wording to define the grouping rule and map samples conservatively.
6. Produce a table with at least `sample_accession`, `group`, `evidence`, and `confidence`.

Guidelines:

- Prefer explicit ENA metadata fields such as `host_phenotype`, `disease`, `condition`, `diagnosis`, `treatment`, `response`, `case_control`, or similarly named columns before using looser text inference.
- Treat missing or ambiguous metadata as unresolved rather than forcing a label.
- If the study includes more than two cohorts, preserve the original cohort structure instead of collapsing to disease vs control.
- When the paper and ENA metadata disagree, call that out explicitly.
- Show the exact columns or text snippets that justify each grouping rule.

Useful commands:

```bash
uv run --with requests python3 scripts/get_ena_project_samples.py <PROJECT_ACCESSION> -o sample_metadata.csv
uv run --with requests python3 scripts/get_abstracts.py <PMCID_OR_PMID>
uv run --with requests python3 scripts/get_disease_entities.py <PMCID_OR_PMID>
```

Expected output:

- A short explanation of the grouping rule.
- A CSV or TSV with one row per sample.
- An unresolved bucket for samples that cannot be assigned confidently.
