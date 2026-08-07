from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = (
    ".github/workflows/v10-robust-high-roi.yml",
    ".github/workflows/v11-portfolio-high-roi.yml",
    ".github/workflows/v11-robust-portfolio.yml",
    ".github/workflows/v12-market-blend-ranking.yml",
    ".github/workflows/v13-constrained-roi-200-search.yml",
    ".github/workflows/v6-course-policy-analysis.yml",
    ".github/workflows/v6-course-policy-v2-analysis.yml",
    ".github/workflows/v6-regime-policy-analysis.yml",
    ".github/workflows/v6-rolling-oos-analysis.yml",
    ".github/workflows/v6-shadow-analysis.yml",
    ".github/workflows/v6-sparse-budget-analysis.yml",
    ".github/workflows/v6-ticket-ev-analysis.yml",
    ".github/workflows/v7-enriched-ranking-analysis.yml",
    ".github/workflows/v7-full-period-analysis.yml",
    ".github/workflows/v7-regime-policy-analysis.yml",
    ".github/workflows/v8-1-enriched-revalidation.yml",
    ".github/workflows/v8-clean-data-revalidation.yml",
    ".github/workflows/v9-loss-decomposition.yml",
)

removed = []
for relative in LEGACY:
    path = ROOT / relative
    if path.exists():
        path.unlink()
        removed.append(relative)

print(f"Removed {len(removed)} legacy versioned exploration workflows")
for path in removed:
    print(path)
