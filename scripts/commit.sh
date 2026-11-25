#!/usr/bin/env bash
# Commit whatever the agent changed and push, retrying if another agent pushed first.
set -e
git config user.name "ndu-agents[bot]"
git config user.email "ndu-agents@users.noreply.github.com"
git add -A data status store agents
git diff --cached --quiet && { echo "nothing to commit"; exit 0; }
git commit -q -m "$1"
for i in 1 2 3 4 5; do
  git pull -q --rebase -X theirs origin main && git push -q origin HEAD:main && exit 0
  sleep $((i * 5))
done
echo "push failed after 5 attempts"; exit 1
