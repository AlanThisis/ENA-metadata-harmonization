# ENA Metadata Harmonization

Claude Code plugin for classifying microbiome samples from ENA studies into labeled cohorts (disease, control, or other) using ENA metadata, paper abstracts, and MeSH disease annotations.

## Install

```
/plugin marketplace add AlanThisis/ENA-metadata-harmonization
/plugin install microbiome-harmonization@mmc-plugins
```

Requires [`uv`](https://github.com/astral-sh/uv) on your PATH.

## Usage

### Main skill: Harmonize cohorts

```
/microbiome-harmonization:harmonize <PMID_or_PMCID> <ENA_ACCESSION>
```

Given a paper ID and ENA project accession, the skill:
1. Fetches the paper abstract and MeSH disease annotations
2. Retrieves sample-level ENA metadata
3. Uses Claude to classify each sample as disease/control/other based on explicit metadata fields, alias patterns, abstract language, and disease annotations
4. Extracts phenotypic data (age, sex, disease) when available
5. Outputs whether the cohorts are separable and confidence per assignment

**Example:**

```
/microbiome-harmonization:harmonize PMC10797958 PRJEB46665
```

**What you're classifying:**
- **Paper**: [PMC10797958 on PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC10797958/) — abstract and disease context
- **Study**: [PRJEB46665 on ENA](https://www.ebi.ac.uk/ena/browser/view/PRJEB46665) — sample metadata
- **Disease annotations**: [PubTator3 view](https://www.ncbi.nlm.nih.gov/research/pubtator3/publication/25432777) for the PMID (PubTator extracts MeSH terms)
- **Example sample**: [SAMEA9544267](https://www.ebi.ac.uk/ena/browser/view/SAMEA9544267) — shows host age, sex, and disease status in metadata

**Output CSV** includes:
- `sample_accession`: ENA sample ID
- `label`: disease / control / other / unresolved
- `label_source`: which signal assigned it (explicit field, alias pattern, text inference, or abstract reconciliation)
- `confidence`: high / medium / low
- `age`, `sex`, `disease`: phenotypic metadata (when found)
- `separable`: true/false — whether the dataset can be reliably split into cohorts
- `notes`: explanation of how labels were assigned and any ambiguities

### Individual scripts

The plugin includes three standalone scripts available via `uv run --with requests python3`:

#### Get abstracts

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_abstracts.py <PMID_or_PMCID>
```

Fetches abstract text from NCBI PubMed/PMC. Single ID prints text; multiple IDs produce CSV.

#### Get disease entities

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_disease_entities.py <PMID_or_PMCID>
```

Retrieves MeSH disease annotations from PubTator3. Single ID prints one disease per line (name<TAB>mesh_id); multiple IDs produce CSV.

#### Get ENA sample metadata

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_project_samples.py <ENA_ACCESSION> -o samples.csv
```

Fetches flattened sample-level metadata from ENA. Use `--max-samples N` for quick tests on large studies.

#### Get ENA accessions from paper

```bash
uv run --with requests python3 ${CLAUDE_PLUGIN_ROOT}/scripts/get_ena_accession.py <PMID_or_PMCID>
```

Fetches PMC full-text XML and extracts ENA/SRA project accessions via regex. Single ID prints accessions one per line; multiple IDs produce CSV.

## Local development

```bash
claude --plugin-dir ./plugins/microbiome-harmonization
```
