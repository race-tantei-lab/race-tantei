# Production verification

The production gate verifies the deployed Cloudflare Worker rather than only compiling the repository.

## Permanent gate

It requires all of the following:

- `/health` returns `ok: true` with model `v2.0.1-live`
- the public homepage renders
- JRA race sources are discovered and stored in production D1
- at least one race is stored and returned from `/api/races`

The live integration suite separately reads the official JRA pages for the current Sapporo 5R and verifies entry runners, odds, results, payouts, and full Saturday/Sunday race discovery.

## Final production evidence — 2026-08-01

The one-time final production verification completed successfully against the public Worker and production D1.

- Worker health: `ok: true`
- Model: `v2.0.1-live`
- Live JRA integration: Sapporo 5R parsed with 13 runners, 13 results, and 12 payouts
- Live discovery test: 36 races for 2026-08-01 and 36 races for 2026-08-02
- Production race sources stored: 76
- Production races returned by `/api/races`: 40
- Existing Sapporo 5R name corrected to `メイクデビュー札幌`
- Completed production Cron run:
  - discovered: 72
  - processed: 12
  - successful: 12
  - errors: 0

The strict verification workflow was intentionally closed without merging because its fixed threshold of 72 races applies only to this three-venue weekend. The permanent smoke test uses nonzero production data as its portable requirement.

## Scope

This verifies that the application is deployed, discovers current JRA races, parses official race data, writes to production D1, and serves the stored races publicly. It does not claim or guarantee a future betting return. Return on investment remains an observed performance metric accumulated from predictions locked before post time.
