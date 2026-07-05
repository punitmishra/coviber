# Contributing to CoViber

Thanks for helping! CoViber grows mainly through **new loaders** — new sources of
context. That's the highest-value contribution.

## Ground rules
- **No proprietary or personal data.** Ever. The demo corpus is synthetic and must
  stay that way. PRs adding real data, scraped employer content, or non-synthetic
  fixtures will be closed.
- **Core stays dependency-light.** Put heavy deps behind an extra in `pyproject.toml`
  and import them lazily inside the module that needs them.
- **Local-first.** No feature may require cloud egress or telemetry to work.

## Dev setup
```bash
pip install -e ".[all,dev]"
python -m pytest                  # or: python tests/test_pipeline.py
ruff check .                      # lint (config in pyproject.toml)
python bench/run.py               # reproduce the benchmark
```

## Adding a loader
1. Subclass `Loader` in `coviber/loaders/yourname.py`, decorate with `@register("yourname")`.
2. Yield `Record`s from `load()`.
3. Add a test to `tests/`.
4. If it needs deps, add an extra; import lazily.

## PRs
- Keep them focused; one loader or one fix per PR.
- Include a test and a line in the README loader list.
- AI-assisted PRs are welcome **if** you've run the tests and understand the change.
  Low-effort/untested "slop" PRs will be closed.

By contributing you agree your work is licensed under Apache-2.0.
