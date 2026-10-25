# Windows version of publish.sh.  Run in PowerShell from this folder:   .\publish.ps1
# Needs: git (https://git-scm.com) and GitHub CLI (winget install GitHub.cli)
param([string]$Repo = "uk-lettings-analytics")
$ErrorActionPreference = "Stop"

gh auth status 2>$null; if ($LASTEXITCODE -ne 0) { gh auth login --web --git-protocol https }
$Owner = gh api user --jq .login

if (-not (Test-Path .git)) {
  git init -b main
  git add .
  git commit -m "Lettings Pulse: UK lettings analytics pipeline, risk model and dashboard"
}

gh repo create $Repo --public --source=. --remote=origin --push `
  --description "UK lettings analytics: SQL pipeline, data-quality checks, arrears-risk model and live dashboard (Python, DuckDB, scikit-learn)"

gh api -X POST "repos/$Owner/$Repo/pages" -f "source[branch]=main" -f "source[path]=/docs" | Out-Null
gh repo edit "$Owner/$Repo" --homepage "https://$Owner.github.io/$Repo/" `
  --add-topic data-analytics --add-topic sql --add-topic python --add-topic dashboard --add-topic machine-learning

Write-Host ""
Write-Host "Repo:       https://github.com/$Owner/$Repo"
Write-Host "Live demo:  https://$Owner.github.io/$Repo/   (1-2 minutes to appear the first time)"
