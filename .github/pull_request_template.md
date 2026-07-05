## What & why

<!-- One or two sentences. Keep PRs focused: one loader or one fix per PR. -->

## How it was tested

- [ ] `python -m pytest` is green
- [ ] `ruff check .` is clean
- [ ] `coviber demo` still works (if core was touched)

## Checklist

- [ ] No real, proprietary, or personal data — synthetic fixtures only
- [ ] Heavy dependencies are behind an extra in `pyproject.toml`, imported lazily
- [ ] No cloud egress or telemetry introduced
- [ ] Docs updated (README loader list, etc.) if applicable
