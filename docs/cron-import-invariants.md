# Cron import invariants

The JRA history importer must preserve these invariants:

1. One scheduled invocation processes at most five URLs.
2. The cursor is checkpointed only after every URL in the five-URL group is either stored, skipped as complete, or placed on the retry queue.
3. A multi-race D1 save failure is retried one race at a time so one malformed race cannot abort the other races.
4. A failed URL is retried at most three times before being moved to permanent failures.
5. Permanent failures do not block completion of the remaining history corpus.
