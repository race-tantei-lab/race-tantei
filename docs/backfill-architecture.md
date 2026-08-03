# History backfill architecture

The initial multi-month history load runs as a one-off GitHub Actions job. It downloads immutable JRA result pages with bounded concurrency, parses them outside the Worker request lifecycle, generates transactional SQL chunks, and bulk-loads those chunks into the production D1 database. The minute Cron remains responsible only for incremental recovery and later maintenance.
