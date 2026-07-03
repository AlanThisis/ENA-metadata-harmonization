---
description: "Fetch and analyze microbiome metadata from papers and ENA studies. Extract abstracts, disease annotations, sample metadata, and ENA accessions. Classify samples into cohorts or inspect metadata directly."
---

# Microbiome Metadata

Work with microbiome research data: fetch paper abstracts, retrieve MeSH disease annotations from PubTator3, extract ENA sample metadata, and classify samples into disease/control cohorts.

## Available Tools

> **Script usage rules — read before proceeding:**
> - All API calls (NCBI, PubTator3, ENA) **must go through these scripts**. They enforce rate limits (3 RPS for NCBI/PubTator3, 2 RPS for ENA). Never call these APIs directly.
> - All scripts accept **multiple IDs in a single call** — use batch mode for any list or CSV operation. Do not loop over IDs one at a time.
> - When unsure about a script's flags or output format, run it with `-h` first.

Four scripts are available via `uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/<script>`:

### get_abstracts.py — Fetch paper abstracts

**Usage:**
```
get_abstracts.py <PMID_or_PMCID> [...]  [-o output.csv]
get_abstracts.py --input-csv FILE [--id-column COLUMN] [-o output.csv]
```

Fetches abstract text from NCBI PubMed/PMC. Single ID prints text to stdout; multiple IDs produce CSV. `--input-csv` reads IDs from a CSV column (defaults to first column if `--id-column` is omitted). Progress is printed to stderr. Run with `-h` for full options.

### get_disease_entities.py — Fetch disease annotations

**Usage:**
```
get_disease_entities.py <PMID_or_PMCID> [...]  [-o output.csv]
get_disease_entities.py --input-csv FILE [--id-column COLUMN] [-o output.csv]
```

Retrieves MeSH disease annotations from PubTator3. Single ID prints one disease per line (name<TAB>mesh_id); multiple IDs produce CSV with disease_names and disease_ids (semicolon-separated). Progress is printed to stderr. Run with `-h` for full options.

### get_ena_project_samples.py — Fetch sample metadata

**Usage:**
```
get_ena_project_samples.py <ACCESSION> [-o output.csv] [--max-samples N]
get_ena_project_samples.py --input-csv FILE [--id-column COLUMN] [-o output.csv]
```

Fetches flattened sample-level metadata and writes CSV. Database is auto-detected from the accession prefix:

| Prefix | Database | Notes |
|--------|----------|-------|
| PRJEB, ERP, ERS, SAMEA | ENA | Batch XML, 200 samples/request |
| PRJNA, SRP, DRP | ENA | Primary query + `read_run` fallback (~28% need fallback) |
| PRJCA, CRA | CNCB-GSA | HTML scrape → GWH API per sample, parallelized |

`--input-csv` reads accessions from a CSV (column auto-detected or set with `--id-column`) and concatenates all studies into one output. Outputs `project_accession`, `sample_accession`, `sample_alias`, `sample_title`, plus any study-specific attribute columns. Use `--max-samples N` for quick inspections on large studies. Per-sample progress is printed to stderr. Run with `-h` for full options.

### get_ena_accession.py — Extract ENA accessions from papers

**Usage:**
```
get_ena_accession.py <PMID_or_PMCID> [...]  [-o output.csv]
get_ena_accession.py --input-csv FILE [--id-column COLUMN] [-o output.csv]
```

Fetches PMC full-text XML and extracts ENA/SRA project accessions via regex. Single ID prints accessions one per line; multiple IDs produce CSV. Per-paper progress is printed to stderr. Run with `-h` for full options.

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

- Check which column holds the PMC/PMID values (`head -5` the CSV)
- Pass the CSV directly with `--input-csv` — no need to extract IDs manually
- Run as a background command so output doesn't load into context

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_abstracts.py \
  --input-csv papers.csv --id-column pmcid -o abstracts.csv
```

If the column name is unknown, omit `--id-column` and the script will use the first column and tell you which one it picked. Progress is printed to stderr so you can see it running.

### Find ENA studies from a paper

When you want to know what ENA projects are mentioned in a paper:

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_accession.py <PMID_or_PMCID>
```

### Inspect sample metadata directly

When you want to explore a project without classification:

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_project_samples.py <ACCESSION> -o samples.csv
```

Then probe with shell/Python tools (see CSV Inspection Workflow below).

### Extract phenotype metadata from a CSV of accessions

**Trigger:** user provides a CSV where at least one column contains project/study accessions (PRJEB, PRJCA, CRA, ERP, …). Goal is a combined phenotype table (age, sex, disease) across all studies.

**Step 1 — Identify the accession column and set up output directory**

```bash
head -3 input.csv
```

Find the column whose values match `^(PRJEB|PRJCA|CRA|ERP)\d+`. Name the output directory after the input file:

```bash
mkdir -p input_stem_metadata   # replace input_stem with the CSV filename without extension
```

**Step 2 — Fetch metadata for all accessions in one call**

Pass the CSV directly — the script auto-detects the accession column and concatenates all studies into one output file. Redirect stderr to a log file so progress doesn't flood context:

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_project_samples.py \
  --input-csv input.csv \
  -o input_stem_metadata/all_samples.csv \
  2>input_stem_metadata/fetch.log
```

If the accession column has an ambiguous name, specify it explicitly:

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_project_samples.py \
  --input-csv input.csv --id-column study_accession \
  -o input_stem_metadata/all_samples.csv \
  2>input_stem_metadata/fetch.log
```

Check progress without loading the log into context:

```bash
tail -5 input_stem_metadata/fetch.log
```

**Step 3 — Stage 1 phenotype extraction (regex on column names)**

All studies are now in one file. Run this Python one-liner against the header only — no grep `\b` issues, zero context overhead:

```bash
python3 -c "
import csv, re
AGE_RE = re.compile(r'^age$|^age_|_age$|host_age', re.I)
SEX_RE = re.compile(r'^sex$|^gender$|biological_sex|host_sex', re.I)
DIS_RE = re.compile(r'disease|diagnosis|condition|phenotype|health_state|disease_state|disease_status|case_control|icd|pathology|morbidity', re.I)
with open('input_stem_metadata/all_samples.csv') as f:
    cols = next(csv.reader(f))
print('AGE:', [c for c in cols if AGE_RE.search(c)])
print('SEX:', [c for c in cols if SEX_RE.search(c)])
print('DIS:', [c for c in cols if DIS_RE.search(c)])
"
```

Note the column names. If all three have matches, skip Stage 2 and go directly to Step 5.

**Step 4 — Stage 2 disease review (controlled file read for false negatives)**

Only reach for this when Stage 1 found **no** disease column. Do not read the full CSV.

4a. Read **only the header row** and list all column names with indices:

```bash
head -1 input_stem_metadata/all_samples.csv | tr ',' '\n' | nl
```

Scan the list for columns that could encode disease or group membership: names containing `host_phenotype`, `subject_group`, `clinical_status`, `study_condition`, `body_site`, disease abbreviations (`crc`, `ibd`, `cd`, `uc`, `t2d`), or columns ending in `_type`, `_group`, `_status`. This is LLM judgment — look for anything that a biologist might use to distinguish cases from controls.

4b. For each suspicious column, peek at its first few distinct values — do not read whole rows:

```bash
python3 -c "
import csv
with open('input_stem_metadata/all_samples.csv') as f:
    rows = list(csv.DictReader(f))
col = 'SUSPICIOUS_COLUMN_NAME'
print(list(dict.fromkeys(r[col] for r in rows if r.get(col)))[:5])
"
```

If those values confirm disease signal (e.g. `['CRC', 'Healthy', 'CRC', 'Healthy', 'IBD']`), note the column name — you will use it in Step 5. If nothing surfaces after this pass, leave `disease` blank — do not guess.

**Step 5 — Produce the combined phenotype table**

Run this command to write `phenotype_coverage.csv`. It auto-detects columns using the same patterns as Stage 1. If Stage 2 found a disease column that Stage 1 missed, replace the `dis_col = next(...)` line with `dis_col = 'your_column_name'` before running:

```bash
python3 -c "
import csv, re
AGE_RE = re.compile(r'^age$|^age_|_age$|host_age', re.I)
SEX_RE = re.compile(r'^sex$|^gender$|biological_sex|host_sex', re.I)
DIS_RE = re.compile(r'disease|diagnosis|condition|phenotype|health_state|disease_state|disease_status|case_control|icd|pathology|morbidity', re.I)
SEX_MAP = {'m':'male','male':'male','boy':'male','1':'male',
           'f':'female','female':'female','girl':'female','2':'female'}
with open('input_stem_metadata/all_samples.csv') as fh:
    rows = list(csv.DictReader(fh))
cols = list(rows[0].keys()) if rows else []
age_col = next((c for c in cols if AGE_RE.search(c)), None)
sex_col = next((c for c in cols if SEX_RE.search(c)), None)
dis_col = next((c for c in cols if DIS_RE.search(c)), None)
# If Stage 2 found a disease column not matched above, uncomment and set:
# dis_col = 'your_column_name'
with open('input_stem_metadata/phenotype_coverage.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=['study_accession','sample_accession','age','sex','disease','disease_col_name'])
    w.writeheader()
    for r in rows:
        sex_raw = (r.get(sex_col,'') if sex_col else '').lower().strip()
        w.writerow({'study_accession':r.get('project_accession',''),
            'sample_accession':r.get('sample_accession',''),
            'age':r.get(age_col,'') if age_col else '',
            'sex':SEX_MAP.get(sex_raw,''),
            'disease':r.get(dis_col,'') if dis_col else '',
            'disease_col_name':dis_col or ''})
print(f'Done: {len(rows)} rows  age={age_col!r}  sex={sex_col!r}  disease={dis_col!r}')
"
```

After it prints, report a one-line summary per study: how many samples, which columns were used, and how many samples have a blank disease field.

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

Extract `age`, `sex`, and `disease` when present. Use the two-stage approach — regex first, controlled file read second — as described in the "Extract phenotype metadata from a CSV of accessions" use case above. Never read a full metadata CSV into context.

**Age:** Pattern: `^age$|^age_|_age$|host_age` (case-insensitive, Python `re`). Record raw value; note unit if the column name implies it (e.g., `age_months`). Use `<min>-<max>` if the value is a range.

**Sex:** Pattern: `^sex$|^gender$|biological_sex|host_sex` (case-insensitive). Normalize values: `M`/`male`/`boy`/`1` → `male`; `F`/`female`/`girl`/`2` → `female`; anything else → blank.

**Disease:** Stage 1 pattern: `disease|diagnosis|condition|phenotype|health_state|disease_state|disease_status|case_control|icd|pathology|morbidity` (case-insensitive substring match — these terms don't appear as substrings in unrelated column names, so no word-boundary anchors needed). If no match, do Stage 2 (header scan + value peek on suspicious columns). Capture the specific disease term (e.g., `colorectal cancer`, `inflammatory bowel disease`). Leave blank if nothing surfaces after both stages.

Sex is almost always caught by Stage 1. Disease often needs Stage 2 — always do it before concluding disease is absent.

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
