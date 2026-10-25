#!/usr/bin/env bash
# One-command publish: creates the GitHub repo, pushes the code and turns on
# GitHub Pages so the dashboard is live at https://<you>.github.io/uk-lettings-analytics/
# Needs: git and the GitHub CLI (https://cli.github.com).  Run:  bash publish.sh
set -euo pipefail
REPO="${1:-uk-lettings-analytics}"

gh auth status >/dev/null 2>&1 || gh auth login --web --git-protocol https
OWNER="$(gh api user --jq .login)"

if [ ! -d .git ]; then
  git init -b main
  git add .
  git commit -m "Lettings Pulse: UK lettings analytics pipeline, risk model and dashboard"
fi

gh repo create "$REPO" --public --source=. --remote=origin --push \
  --description "UK lettings analytics: SQL pipeline, data-quality checks, arrears-risk model and live dashboard (Python, DuckDB, scikit-learn)"

gh api -X POST "repos/$OWNER/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null \
  || echo "Pages may already be on - check Settings > Pages"
gh repo edit "$OWNER/$REPO" --homepage "https://$OWNER.github.io/$REPO/" \
  --add-topic data-analytics --add-topic sql --add-topic python --add-topic dashboard --add-topic machine-learning

echo
echo "Repo:       https://github.com/$OWNER/$REPO"
echo "Live demo:  https://$OWNER.github.io/$REPO/   (takes 1-2 minutes to appear the first time)"
