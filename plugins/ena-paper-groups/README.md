# ena-paper-groups

Local Claude Code plugin for ENA study/sample cohort extraction.

## Local testing

Run Claude Code with the plugin loaded from this repository:

```bash
claude --plugin-dir ./plugins/ena-paper-groups
```

Then invoke the skill:

```text
/ena-paper-groups:separate-samples
```

After editing the plugin files, run:

```text
/reload-plugins
```
