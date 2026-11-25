#!/usr/bin/env bash
# Commit what this agent changed and push. Agents run in parallel, so on a rejected push:
# rebase onto the latest main (own files win), rebuild the shared feeds from everyone's files, retry.
set -e
git config user.name "ndu-agents[bot]"
git config user.email "ndu-agents@users.noreply.github.com"
git add -A data status store agents
git diff --cached --quiet && { echo "nothing to commit"; exit 0; }
git commit -q -m "$1"
for i in 1 2 3 4 5 6; do
  git push -q origin HEAD:main && exit 0
  sleep $((i * 4))
  git fetch -q origin main
  git rebase -q -X theirs origin/main || { git checkout -q --theirs . 2>/dev/null; git add -A; GIT_EDITOR=true git rebase --continue; }
  python -m workers.catalog >/dev/null
  git add -A data status
  git diff --cached --quiet || git commit -q --amend --no-edit
done
echo "push failed after 6 attempts"; exit 1
