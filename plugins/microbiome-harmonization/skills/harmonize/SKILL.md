---
description: "Fetch and analyze microbiome metadata from papers and ENA studies. Extract abstracts, disease annotations, sample metadata, and ENA accessions. Classify samples into cohorts or inspect metadata directly."
---

# Microbiome Metadata

Work with microbiome research data: fetch paper abstracts, retrieve MeSH disease annotations from PubTator3, extract ENA sample metadata, and classify samples into disease/control cohorts.

## Available Tools

Four scripts are available via `uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/<script>`:

### get_abstracts.py — Fetch paper abstracts

**Usage:** `get_abstracts.py <PMID_or_PMCID> [<PMID_or_PMCID> ...] [-o output.csv]`

Fetches abstract text from NCBI PubMed/PMC. Single ID prints text to stdout; multiple IDs produce CSV. Run with `-h` for full options.

### get_disease_entities.py — Fetch disease annotations

**Usage:** `get_disease_entities.py <PMID_or_PMCID> [<PMID_or_PMCID> ...] [-o output.csv]`

Retrieves MeSH disease annotations from PubTator3. Single ID prints one disease per line (name<TAB>mesh_id); multiple IDs produce CSV with disease_names and disease_ids (semicolon-separated). Run with `-h` for full options.

### get_ena_project_samples.py — Fetch ENA sample metadata

**Usage:** `get_ena_project_samples.py <ENA_ACCESSION> [-o output.csv] [--max-samples N]`

Fetches flattened sample-level metadata from ENA. Outputs project_accession, sample_accession, sample_alias, sample_title, plus any custom SAMPLE_ATTRIBUTE fields. Use `--max-samples N` for quick inspections on large studies. Run with `-h` for full options.

### get_ena_accession.py — Extract ENA accessions from papers

**Usage:** `get_ena_accession.py <PMID_or_PMCID> [<PMID_or_PMCID> ...] [-o output.csv]`

Fetches PMC full-text XML and extracts ENA/SRA project accessions via regex. Single ID prints accessions one per line; multiple IDs produce CSV. Run with `-h` for full options.

---

## Use Cases

### Classify samples into disease/control cohorts

When you have a paper ID and ENA project accession, use this workflow:

1. Fetch the abstract to understand study design
2. Get MeSH disease annotations
3. Retrieve sample metadata
4. Probe the sample data for case/control signal
5. Classify each sample based on available signals
6. Produce output with assignments and confidence scores

Ask the user for output format preferences (what columns, where to save) if not specified.

### Bulk-fetch abstracts from a CSV

When you have a CSV with paper IDs and want abstracts without token overhead:

- Ask which column contains the PMC/PMID values
- Extract that column and pipe to `get_abstracts.py`
- Run as a background command and report when done (don't read the output into context)

Example (for CSV with PMC IDs in column 2):
```bash
cut -d',' -f2 your_data.csv | tail -n +2 | tr '\n' ' ' | xargs python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_abstracts.py -o abstracts.csv
```

Or in Python for more control:
```python
python3 << 'EOF'
import csv, subprocess
with open('your_data.csv') as f:
    ids = [row[column_index] for row in csv.reader(f)]
subprocess.run(['python3', '${CLAUDE_PLUGIN_ROOT}/scripts/get_abstracts.py'] + ids + ['-o', 'abstracts.csv'])
EOF
```

### Find ENA studies from a paper

When you want to know what ENA projects are mentioned in a paper:

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_accession.py <PMID_or_PMCID>
```

### Inspect sample metadata directly

When you want to explore an ENA project without classification:

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_project_samples.py <ENA_ACCESSION> -o samples.csv
```

Then probe with shell/Python tools (see CSV Inspection Workflow below).

---

## CSV Inspection Workflow

The sample CSV can be large. Always start by understanding the structure before diving into analysis.

**Step 1 — Inspect raw data:**

```bash
wc -l /path/to/samples.csv
head -5 /path/to/samples.csv
```

This shows file size and raw data, including how fields are quoted and whether commas are embedded in values.

**Step 2 — Choose your probing approach:**

Based on what you see in `head -5`, pick a strategy. Here are common approaches — **be creative and combine them:**

```bash
# List all columns
head -1 /path/to/samples.csv | tr ',' '\n' | nl

# Count unique values in a column (e.g., column 5)
cut -d, -f5 /path/to/samples.csv | tail -n +2 | sort | uniq -c

# Search for specific keywords in headers
head -1 /path/to/samples.csv | grep -io 'disease\|health\|age\|sex\|phenotype'

# Extract and summarize multiple columns with Python
python3 -c "import csv; rows=list(csv.reader(open('/path/to/samples.csv'))); print(f'Columns: {rows[0]}'); [print(f'{rows[0][i]}: {set(r[i] for r in rows[1:] if i<len(r))}') for i in range(min(5, len(rows[0])))]"

# Use awk to filter/extract columns
awk -F',' '{print $1, $5, $6}' /path/to/samples.csv | sort | uniq -c

# Quick Python one-liner to inspect a specific column
python3 -c "import csv; c=[r[3] for r in csv.reader(open('/path/to/samples.csv'))]; from collections import Counter; print(Counter(c).most_common(10))"
```

**Important:** If `head -5` shows quoted fields with commas inside (e.g., `"text, with comma"`), use Python's csv module or jq rather than simple `cut -d','` — splitting on commas alone will miscount columns.

**Step 3 — Iterate and refine:**

Based on what you discover, keep probing. Look for patterns in column names and values. Search for abbreviations, typos, domain-specific terms. The data will guide you.

---

## Sample Classification Workflow

When classifying samples into cohorts, work through these signal levels. Stop at the first level that gives confident results.

### Signal Probe Order

**Level 1 — Explicit metadata columns**

Look for columns that directly encode cohort information. Start with these keywords: `disease`, `health_state`, `host_disease`, `host_phenotype`, `diagnosis`, `condition`, `case_control`, `treatment`, `phenotype`, `subject_disease_status`, `disease_status`.

**Be creative:** Also check for abbreviated or domain-specific variations (`crc`, `ibd`, `cd`, `uc`, `t2d`, `normal_vs_disease`), typos, or columns that end in `_status`, `_type`, `_group`. Scan the actual column names in your data — they often hint at the field purpose.

Common value patterns when found:
- Disease: `case`, `disease`, `patient`, `affected`, `positive`, or columns named after diseases
- Control: `control`, `healthy`, `HC`, `HV`, `normal`, `unaffected`, `negative`

**Label source:** `explicit_field`

**Level 2 — Sample alias / title patterns**

Inspect `sample_alias` and `sample_title` for structured naming. Common examples:
- `CRC_01`, `CRC01` → colorectal cancer case
- `HC_01`, `HV_01`, `NC_01` → healthy control
- `CD_`, `UC_`, `IBD_` → inflammatory bowel disease subtypes
- `T2D_`, `HbA1c_` → metabolic disease
- `BRC_`, `BRCA_` → breast cancer

**Be creative:** Look for other prefixes or suffixes (e.g., `disease_`, `normal_`, sample ID patterns that encode group membership). Extract the pattern and apply uniformly.

**Label source:** `alias_pattern`

**Level 3 — Free-text fields**

Scan `description`, `sample_title`, and other string columns for disease/control keywords. Use this only when Levels 1–2 yield no signal.

**Label source:** `free_text` → assign `confidence: low`

**Level 4 — Abstract reconciliation**

Use the paper's abstract to infer group structure when metadata alone is insufficient:
- Extract stated group sizes and labels from the abstract
- Map unresolved samples by count (e.g., if abstract says N=40 CRC and N=40 healthy, assign unresolved samples by process of elimination with `confidence: low`)
- Note any discrepancy between ENA sample count and abstract N in `notes`

**Label source:** `abstract_reconciliation` → assign `confidence: low`

### Phenotypic Data Extraction

Extract `age`, `sex`, and `disease` when present. Most ENA studies lack this, but capture when available.

**Age:** Look for columns named `age`, `age_at_collection`, `host_age`, `age_years`, or numeric columns with plausible age ranges. Also check columns ending in `_age` or `_years`. Record as `<value>` or `<min>-<max>` if a range.

**Sex:** Check columns `sex`, `gender`, `host_sex`, `biological_sex`. Normalize: `M` / `male` / `boy` → `male`; `F` / `female` / `girl` → `female`; `other` / `not_determined` → blank. Be creative with variations (e.g., `sex_biological`, `gender_assigned`).

**Disease:** Capture the specific disease term (e.g., `colorectal cancer`, `inflammatory bowel disease`) from metadata or abstract.

Leave blank if not found.

---

## Output & Schema

Before starting classification, ask the user:

- **What output format?** CSV, TSV, JSON?
- **Which columns are essential?** (e.g., do they need phenotypic data, confidence scores, notes?)
- **Where should the output go?** (suggest a user-specified directory, or `/tmp/` if they have no preference)

**Suggested default schema for cohort classification** (adjust based on user needs):

| Column | Values | Purpose |
|--------|--------|---------|
| `sample_accession` | e.g. `SAMEA12345` | Sample ID from ENA |
| `study_accession` | e.g. `PRJEB46665` | Input project/study accession |
| `pmid` | numeric string or blank | Resolved paper PMID |
| `mesh_term` | e.g. `colorectal neoplasms` | Raw MeSH disease term(s) from PubTator3 |
| `canonical_disease` | e.g. `colorectal cancer`, `IBD` | Standardized disease label derived from MeSH and abstract |
| `label` | `disease` / `control` / `other` / `unresolved` | Sample cohort assignment |
| `label_source` | `explicit_field` / `alias_pattern` / `free_text` / `abstract_reconciliation` | Which probe level assigned this label |
| `control_type` | e.g. `healthy_volunteer`, `adjacent_normal` | Type of control (if applicable; blank for non-controls) |
| `confidence` | `high` / `medium` / `low` | Confidence in the assignment |
| `age` | e.g. `42`, `18-65` | Phenotypic age (blank if not found) |
| `sex` | `male` / `female` | Phenotypic sex, normalized (blank if not found) |
| `disease` | e.g. `colorectal cancer` | Phenotypic disease term (blank if not found) |
| `separable` | `true` / `false` | Whether dataset can be reliably split into cohorts |
| `notes` | free text | Required for `confidence: low/medium`, `separable: false`, or metadata/abstract disagreements |

### Classification Rules

- Never force a label onto an ambiguous sample. Use `unresolved`.
- If the study has more than two cohorts, preserve all of them — do not collapse to disease vs control.
- If ENA metadata and abstract disagree on group structure or sample counts, set `confidence: low` on affected rows and explain in `notes`.
- `separable: false` applies at the dataset level when metadata is too sparse or inconsistent to support reliable cohort splitting. Always explain why in `notes`.
- For any assignment with `confidence: medium` or lower, quote the exact column name or text snippet that justified it in `notes`.

### API Resilience

All scripts hit external APIs (NCBI Entrez, PubTator3, ENA). If any call fails, report the error and continue with available data rather than aborting. Rate-limiting is built in (3 RPS for NCBI, 2 RPS for ENA).
