# Repository Guidelines

## Project Structure & Module Organization

This repository currently centers on small Python CLIs for ENA and literature metadata retrieval.

- `scripts/`: executable utilities (local dev copies)
  - `get_abstracts.py`: PMID/PMCID to abstract text
  - `get_disease_entities.py`: PMID/PMCID to PubTator disease entities
  - `get_ena_project_samples.py`: ENA project accession to flattened sample metadata CSV
- `.claude-plugin/marketplace.json`: marketplace catalog for Claude Code plugin distribution
- `plugins/microbiome-harmonization/`: Claude Code plugin for cohort harmonization
  - `.claude-plugin/plugin.json`: plugin manifest (name, version, description)
  - `scripts/`: bundled copies of the three CLI scripts (required for marketplace install)
  - `skills/harmonize/SKILL.md`: main skill — invoked as `/microbiome-harmonization:harmonize <PMID> <ENA_ACCESSION>`

Keep new automation scripts in `scripts/`. Put Claude plugin assets under `plugins/<plugin-name>/`.

## Build, Test, and Development Commands

Use `uv run --with requests` for local execution so dependencies stay ephemeral.

- `uv run --with requests python3 scripts/get_abstracts.py PMC3531190`
- `uv run --with requests python3 scripts/get_disease_entities.py PMC10797958`
- `uv run --with requests python3 scripts/get_ena_project_samples.py PRJEB46665 --max-samples 2`
- `uv run --with requests python3 -m py_compile scripts/get_abstracts.py scripts/get_disease_entities.py scripts/get_ena_project_samples.py`

For plugin development:

- `claude --plugin-dir ./plugins/microbiome-harmonization`
- Then run `/microbiome-harmonization:harmonize <PMID_or_PMCID> <ENA_ACCESSION>`
- Use `/reload-plugins` after editing plugin files

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, standard library first, then third-party imports. Favor small, single-purpose scripts and explicit `argparse` CLIs. Use snake_case for functions, variables, and file names. Keep network calls rate-limited and handle partial failures with clear error messages.

## Testing Guidelines

There is no formal test suite yet. At minimum:

- run `py_compile` on edited scripts
- run one live CLI example
- for ENA project export, prefer `--max-samples` for smoke tests on large studies

If you add tests later, place them in `tests/` and name files `test_<module>.py`.

## Commit & Pull Request Guidelines

Follow the existing commit style: short, scoped subjects such as:

- `scripts: add abstract fetch CLI`
- `plugin: add local ENA paper groups scaffold`

Keep commits atomic and stage only touched paths. PRs should state the user-facing behavior, example commands used for verification, and any API or rate-limit assumptions.

## Security & Configuration Tips

Do not hardcode credentials or edit `.env` files. Prefer ephemeral dependencies via `uv run --with ...`. Respect upstream API limits for NCBI, PubTator, and ENA; conservative throttling is expected in all new networked scripts.
