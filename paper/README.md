# CoViber whitepaper

**Title:** *Continuous Context Replication for AI-Augmented Knowledge Work.*
**Target venue:** arXiv (cs.IR / cs.CL / cs.AI).
**Status:** first draft — see below for what still needs work before submission.

## Layout

```
paper/
├── whitepaper.tex         # top-level; \input{}s the section files below
├── references.bib         # bibliography, currently placeholder entries
├── Makefile               # `make` builds whitepaper.pdf via pdflatex+bibtex
├── UNRESOLVED.md          # every open citation and every eval-number placeholder
├── README.md              # this file
└── sections/
    ├── abstract-intro.tex
    ├── related-work.tex
    ├── architecture.tex
    ├── record-loader.tex
    ├── workgraph.tex
    ├── urgency.tex
    ├── persona.tex
    ├── store-vectors.tex
    ├── mcp-interface.tex
    ├── evaluation.tex
    ├── discussion.tex
    └── appendix.tex
```

## Build

Any modern TeX distribution works.

```bash
cd paper/
make          # produces whitepaper.pdf
make clean    # remove aux files
```

macOS: `brew install --cask mactex-no-gui`.
Ubuntu: `sudo apt install texlive-full`.

## How this draft was produced

The section drafts came out of an adversarial workflow (task
`w0wqitbq7`, 24 agents, 1.5M subagent tokens):

1. **Draft phase.** One agent per section drafted LaTeX directly from
   the shipped code (every algorithmic claim traced to a source file
   before writing).
2. **Verify phase.** A skeptic reviewer read each section against the
   code and refuted anything unsupported.

Of the 12 sections:

- **4 verified clean:** `workgraph`, `urgency`, `mcp-interface`,
  `discussion`.
- **8 refuted** with specific factual claims flagged. Each refuted
  `.tex` file has a `% Refutation notes:` block at the top listing what
  needs fixing. Examples: "9 signals cited but urgency.py has 10 keys",
  "protocol described as 6 methods but VectorStore has 7", "Loader
  characterized as ~10 lines but shipped loaders are 40–150".

The refutations are the useful part — every one is a concrete factual
correction, not a stylistic quibble. Fixing them is the next pass.

## Path to submission

The paper is not submission-ready. To get there:

1. **Fix the refuted sections.** Each has a comment block at the top of
   its `.tex` file. This is ~1-2 hours of careful editing.
2. **Fill in eval numbers.** `UNRESOLVED.md` lists 13 `\SI{XXX}{...}`
   placeholders. The bench harness upgrade (PR
   [#56](https://github.com/punitmishra/coviber/pull/56), issue
   [#48](https://github.com/punitmishra/coviber/issues/48)) already
   emits machine-readable JSON at 1k / 10k / 100k. Wire those numbers in.
3. **Fix the citations.** `UNRESOLVED.md` lists 50 `\cite{TODO-...}`
   entries. Most are standard prior-work references (RAG, MCP spec,
   memory-framework docs, stylometry survey); a few need a specific
   search.
4. **Add the architecture figure.** `sections/architecture.tex` notes
   a placeholder for `figures/architecture.svg` — draw it in tikz or
   an external tool.
5. **Ethics + broader impact paragraph** — the appendix has a first
   pass; refine before submission.
6. **arXiv-specific.** The project uses `article` class here; arXiv
   accepts that. If you want a two-column look, swap to
   [`arxiv.sty`](https://github.com/kourgeorge/arxiv-style) before the
   final build. Verify the metadata block (title/author/date) and add
   `\usepackage{arxiv}` if you switch.

Once the above lands, the paper closes issue
[#16](https://github.com/punitmishra/coviber/issues/16).

## Reproducibility

Every number the paper reports can be regenerated with `python bench/run.py`
(harness lives in the repo root, not here). The eval section explicitly
points at `bench/results/*.json` files as the source of truth.
