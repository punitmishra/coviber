#!/bin/bash
set -euo pipefail

# Only needed in Claude Code on the web — local devs manage their own env.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# The container's PyJWT is debian-owned (no RECORD file) and can't be
# uninstalled by pip, but the mcp extra needs a newer one — replace it in place.
python3 -m pip install -q --ignore-installed PyJWT || true

# Core is stdlib-only; [scrape] and [mcp] are small. The [search] extra
# (sentence-transformers → torch) is heavy — install it on demand instead.
python3 -m pip install -q -e ".[scrape,mcp,dev]"
