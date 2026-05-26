---
description: Classify ENA microbiome samples into labeled cohorts (disease, control, or other) given a paper ID and ENA project accession. Invoke as: /microbiome-harmonization:harmonize <PMID_or_PMCID> <ENA_ACCESSION>
---

# Harmonize Microbiome Cohorts

Parse `$ARGUMENTS` as two space-separated tokens:
- Token 1: a PMID (digits only, e.g. `38243197`) or PMCID (e.g. `PMC10797958`)
- Token 2: an ENA project or study accession (e.g. `PRJEB46665`)

If either token is missing or malformed, stop and ask the user to provide both.

---

## Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/scripts/`. Run every script with:

```
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/<script>
```

### get_abstracts.py

```
usage: get_abstracts.py [-h] [-o OUTPUT] ids [ids ...]

Fetch abstract text for PMID/PMCID input(s).

positional arguments:
  ids          One or more PMIDs or PMCIDs (e.g. 27102758 or PMC3531190)

options:
  -h, --help   show this help message and exit
  -o OUTPUT    Write CSV output to this path. If omitted, CSV is printed to stdout for multi-ID input.

Single ID: prints abstract text directly to stdout.
Multiple IDs: produces CSV with columns: requested_id, input_type, pmid, pmcid, abstract, error.
```

### get_disease_entities.py

```
usage: get_disease_entities.py [-h] [-o OUTPUT] ids [ids ...]

Fetch PubTator3 disease entities for PMID/PMCID input(s).

positional arguments:
  ids          One or more PMIDs or PMCIDs (e.g. 38243197 or PMC10797958)

options:
  -h, --help   show this help message and exit
  -o OUTPUT    Write CSV output to this path. If omitted, CSV is printed to stdout for multi-ID input.

Single ID: prints one disease per line as name<TAB>mesh_id.
Multiple IDs: produces CSV with columns: requested_id, input_type, pmid, pmcid, disease_names, disease_ids, error.
disease_names and disease_ids are semicolon-separated when multiple entities exist.
```

### get_ena_project_samples.py

```
usage: get_ena_project_samples.py [-h] [-o OUTPUT] [--max-samples N] project_accession

Fetch ENA sample metadata for a project/study accession and flatten it into CSV.

positional arguments:
  project_accession   ENA project/study accession (e.g. PRJEB46665)

options:
  -h, --help          show this help message and exit
  -o OUTPUT           Write CSV to this path. If omitted, CSV is printed to stdout.
  --max-samples N     Only fetch the first N sample accessions. Use for smoke tests on large studies.

Output columns: project_accession, sample_accession, sample_alias, sample_title, center_name,
primary_id, secondary_id, taxon_id, scientific_name, description, error, then any additional
SAMPLE_ATTRIBUTE fields found in the XML (normalized to snake_case).
```

---

## Workflow

Run these steps in order. Save outputs to temp files with `-o` so you can probe them with shell tools.

**Step 1 — Fetch ENA sample metadata**

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_project_samples.py <ENA_ACCESSION> -o /tmp/samples.csv
```

For studies with more than 200 samples, first run with `--max-samples 10` to inspect the column structure before fetching all samples.

**Step 2 — Fetch abstract**

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_abstracts.py <PMID_or_PMCID>
```

Read the abstract carefully. Note: stated group sizes, cohort names, inclusion/exclusion criteria, and any sample count that can be used to verify the split.

**Step 3 — Fetch MeSH disease entities**

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_disease_entities.py <PMID_or_PMCID>
```

Use these to set `mesh_term` and inform `canonical_disease` in the output.

**Step 4 — Probe the sample CSV for case/control signal**

Follow the Signal Probe Order below. Use `head -1 /tmp/samples.csv` to list columns, then inspect relevant ones with `cut -d, -f<N> /tmp/samples.csv | sort | uniq -c`.

**Step 5 — Assign labels and produce output CSV**

Apply the labeling rules, then write a CSV with the Output Schema below.

---

## Signal Probe Order

Stop at the first probe level that assigns a confident label to most samples. Record which level resolved the label in `label_source`.

**Level 1 — Explicit metadata columns** (`label_source: explicit_field`)

Check for columns named (case-insensitive, partial match acceptable):
`disease`, `health_state`, `host_disease`, `host_phenotype`, `diagnosis`, `condition`, `case_control`, `treatment`, `phenotype`, `subject_disease_status`, `disease_status`

If found, use the column values directly. Common value patterns:
- Disease: `case`, `disease`, `patient`, `affected`, `positive`, column named after a disease
- Control: `control`, `healthy`, `HC`, `HV`, `normal`, `unaffected`, `negative`

**Level 2 — Sample alias / title patterns** (`label_source: alias_pattern`)

Inspect `sample_alias` and `sample_title` for structured prefixes or suffixes. Common examples:
- `CRC_01`, `CRC01` → colorectal cancer case
- `HC_01`, `HV_01`, `NC_01` → healthy control
- `CD_`, `UC_`, `IBD_` → inflammatory bowel disease subtypes
- `T2D_`, `HbA1c_` → metabolic disease
- `BRC_`, `BRCA_` → breast cancer

Extract the prefix/suffix pattern; apply it uniformly to all samples with that pattern.

**Level 3 — Free-text fields** (`label_source: free_text`)

Scan `description`, `sample_title`, and any other string columns for disease/control keywords. Use this level only when Levels 1–2 yield no signal. Assign `confidence: low` for any label derived here.

**Level 4 — Abstract reconciliation** (`label_source: abstract_reconciliation`)

Use the abstract to infer group structure when metadata alone is insufficient:
- Extract stated group sizes and labels from the abstract
- Map unresolved samples by count: if abstract says N=40 CRC and N=40 healthy and metadata assigns 40 samples to neither level 1–3, assign by process of elimination with `confidence: low`
- If sample count in ENA does not match stated N in abstract, note the discrepancy in `notes`

---

## Output Schema

Produce a CSV with exactly these columns in this order:

| Column | Values | Notes |
|---|---|---|
| `sample_accession` | e.g. `SAMEA12345` | from ENA |
| `study_accession` | e.g. `PRJEB46665` | the input accession |
| `pmid` | numeric string | resolved from input; blank if unavailable |
| `mesh_term` | raw MeSH disease term | from PubTator3; semicolon-separated if multiple |
| `canonical_disease` | e.g. `colorectal cancer`, `IBD` | standardized label derived from mesh_term and abstract |
| `label` | `disease` / `control` / `other` / `unresolved` | |
| `label_source` | `explicit_field` / `alias_pattern` / `free_text` / `abstract_reconciliation` | the probe level that assigned this label |
| `control_type` | e.g. `healthy_volunteer`, `adjacent_normal`, `antibiotic_naive` | blank when label is not `control` |
| `confidence` | `high` / `medium` / `low` | |
| `separable` | `true` / `false` | whether the dataset can be reliably split into cohorts |
| `notes` | free text | required when `separable=false`, `confidence=low`, or when ENA metadata and abstract disagree |

---

## Rules

- Never force a label onto an ambiguous sample. Use `unresolved`.
- If the study has more than two cohorts, preserve all of them — do not collapse to disease vs control.
- If ENA metadata and abstract disagree on group structure or sample counts, set `confidence: low` on affected rows and explain in `notes`.
- `separable: false` applies at the dataset level when metadata is too sparse or inconsistent to support reliable cohort splitting. Always explain why in `notes`.
- Quote the exact column name or text snippet that justified each label in `notes` for any `confidence: medium` or lower assignment.
- All three scripts hit external APIs (NCBI Entrez, PubTator3, ENA). If any call fails, report the error and continue with available data rather than aborting.
