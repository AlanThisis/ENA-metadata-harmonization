# Repository Guidelines

## Project Structure & Module Organization

This repository currently centers on small Python CLIs for ENA and literature metadata retrieval.

- `scripts/`: executable utilities
  - `get_abstracts.py`: PMID/PMCID to abstract text
  - `get_disease_entities.py`: PMID/PMCID to PubTator disease entities
  - `get_ena_project_samples.py`: ENA project accession to flattened sample metadata CSV
- `plugins/ena-paper-groups/`: local Claude Code plugin scaffold
  - `.claude-plugin/plugin.json`: plugin manifest
  - `skills/separate-samples/SKILL.md`: skill entrypoint

Keep new automation scripts in `scripts/`. Put Claude plugin assets under `plugins/<plugin-name>/`.

## Build, Test, and Development Commands

Use `uv run --with requests` for local execution so dependencies stay ephemeral.

- `uv run --with requests python3 scripts/get_abstracts.py PMC3531190`
- `uv run --with requests python3 scripts/get_disease_entities.py PMC10797958`
- `uv run --with requests python3 scripts/get_ena_project_samples.py PRJEB46665 --max-samples 2`
- `uv run --with requests python3 -m py_compile scripts/get_abstracts.py scripts/get_disease_entities.py scripts/get_ena_project_samples.py`

For plugin development:

- `claude --plugin-dir ./plugins/ena-paper-groups`
- Then run `/ena-paper-groups:separate-samples`
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
