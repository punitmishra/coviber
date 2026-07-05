# Datasheet — CoViber synthetic corpus

Following *Datasheets for Datasets* (Gebru et al., 2021).

## Motivation
The corpus exists so CoViber runs, tests, and benchmarks **without any real
personal or proprietary data**. It is the reference input for `coviber demo` and
`bench/run.py`, and the substrate for all published numbers in this repo.

## Composition
- **Source:** `coviber/loaders/demo.py` (also exported to `examples/acme_demo.jsonl`).
- **Size:** 15 base records; the benchmark deterministically scales them (`--scale N`).
- **Entities:** a fictional company, *Acme Robotics*, with fictional people
  (Grace Hopper, Ada Byron, Linus Vega, Margaret Chen), projects (Falcon, Orbit,
  Atlas), and cross-platform records (email, slack, github, tracker, teams).
- **Fields:** the canonical `Record` schema (source, from_name, subject, text,
  channel, url, unread, thread_id, …).
- **Labels:** none required; urgency is computed, not annotated.

## Collection process
Hand-authored to exercise every code path: @mentions, priority senders, action
words, questions, unread/no-reply, age decay, and the skip filter
(bots/newsletters/FYI). Three records are authored by `from_name="you"` so the
inference-free persona engine has voice samples to learn from.

## Preprocessing / cleaning
None. Records are used as-is.

## Uses & limitations
- **Intended:** demos, tests, reproducible micro-benchmarks, tutorials.
- **Not intended:** as a representative sample of real communication volume,
  distribution, or language. Absolute benchmark latencies scale with `--scale`
  and hardware; semantic search persists vectors in `embeddings.json` and
  encodes only new records per query, so the first (cold) query is the upper
  bound and warm queries skip record encoding.

## Distribution & maintenance
Ships in-repo under Apache-2.0. Any resemblance to real organizations or people
is coincidental. Extend it by editing `coviber/loaders/demo.py`.

## Confidentiality statement
100% synthetic and fictional. Contains no third-party, employer, customer, or
personal data of any kind.
