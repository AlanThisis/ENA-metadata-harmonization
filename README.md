# ENA Metadata Harmonization

Claude Code plugin for classifying microbiome samples from ENA studies into labeled cohorts (disease, control, or other) using ENA metadata, paper abstracts, and MeSH disease annotations.

## Install

```
/plugin marketplace add AlanThisis/ENA-metadata-harmonization
/plugin install microbiome-harmonization@mmc-plugins
```

Requires [`uv`](https://github.com/astral-sh/uv) on your PATH.

## Usage

```
/microbiome-harmonization:harmonize <PMID_or_PMCID> <ENA_ACCESSION>
```

Example:

```
/microbiome-harmonization:harmonize PMC10797958 PRJEB46665
```

Outputs a CSV with one row per sample: `sample_accession`, `label` (disease/control/other/unresolved), `label_source`, `confidence`, `separable`, and `notes`.

## Local development

```bash
claude --plugin-dir ./plugins/microbiome-harmonization
```
