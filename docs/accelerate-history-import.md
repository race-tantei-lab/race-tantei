# History import throughput tuning

- Raise official-result import batches from 12 to 36 URLs per successful invocation.
- Reduce streaming feature generation to four races per import step so JRA fetch and D1 writes remain the priority.
- Keep full feature generation at sixteen races per step after official history import completes.
