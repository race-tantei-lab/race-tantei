# History import query-budget invariant

A scheduled history-import invocation must not perform per-race fallback writes after a failed bulk save. A five-race bulk failure is converted into queued failures in one checkpoint-state write; retries are handled one URL per later invocation. This keeps the failure path within the same D1 query budget as the healthy path and prevents the error recorder itself from exceeding the invocation limit.
