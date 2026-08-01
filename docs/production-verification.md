# Production verification

The production gate verifies the deployed Cloudflare Worker rather than only compiling the repository.

It requires all of the following:

- `/health` returns `ok: true` with model `v2.0.1-live`
- the public homepage renders
- JRA race sources are discovered and stored in production D1
- at least one race is stored and returned from `/api/races`

The live integration suite separately reads the official JRA pages for the current Sapporo 5R and verifies entry runners, odds, results, payouts, and full Saturday/Sunday race discovery.
