#!/usr/bin/env bash

set -euo pipefail

SOURCE_BRANCH="${1:-}"
TARGET_BRANCH="${2:-}"
REMOTE="${REMOTE:-origin}"

if [[ -z "$SOURCE_BRANCH" || -z "$TARGET_BRANCH" ]]; then
  echo "Usage: $0 <source-branch> <target-branch>"
  exit 1
fi

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "Repository has no commits yet. Create the first commit before promoting branches."
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before promoting."
  exit 1
fi

git fetch "$REMOTE" --prune

if ! git show-ref --verify --quiet "refs/remotes/$REMOTE/$SOURCE_BRANCH"; then
  echo "Remote branch $REMOTE/$SOURCE_BRANCH does not exist."
  exit 1
fi

if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH"; then
  git checkout "$TARGET_BRANCH"
else
  if git show-ref --verify --quiet "refs/remotes/$REMOTE/$TARGET_BRANCH"; then
    git checkout -b "$TARGET_BRANCH" "$REMOTE/$TARGET_BRANCH"
  else
    git checkout -b "$TARGET_BRANCH" "$REMOTE/$SOURCE_BRANCH"
  fi
fi

git pull --ff-only "$REMOTE" "$TARGET_BRANCH" 2>/dev/null || true
git merge --ff-only "$REMOTE/$SOURCE_BRANCH"
git push "$REMOTE" "$TARGET_BRANCH"

echo "Promoted $REMOTE/$SOURCE_BRANCH -> $REMOTE/$TARGET_BRANCH"
