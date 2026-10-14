#!/usr/bin/env bash
# Secret scan: every line ever added on any branch, plus the tracked files now. Exit 1 on any hit.
#   bash scripts/secret_scan.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PAT='AIza[0-9A-Za-z_-]{35}|sk-(ant-)?[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|hf_[A-Za-z0-9]{30,}|BEGIN [A-Z ]*PRIVATE KEY'
ENV='^\+[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*=\S'
added=$(git log --all -p --no-color | grep -a -c '^+' || true)
hits=$( { git log --all -p --no-color | grep -a -E '^\+' | grep -a -E "$PAT|$ENV" || true; git grep -n -I -E "$PAT" -- . ':!uv.lock' ':!web/pnpm-lock.yaml' || true; } | cut -c1-140)
if [ -n "$hits" ]; then echo "$hits"; echo "secret scan: FOUND (see above)"; exit 1; fi
echo "secret scan: clean ($added added lines across $(git rev-list --all --count) commits, plus the tracked files)"
