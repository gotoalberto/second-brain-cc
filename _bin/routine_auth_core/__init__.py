"""Which credential a routine run uses, and what happens when it is refused.

The guardian (guardian_core) answers "is Brain wired right"; this package answers a
question tasks.py needs live, while a routine runs: which token from the pool to inject,
how to read the CLI's failure, and whether to try the next token or stop and alert.

- domain.py       pure rules: classify a failed run, validate a token's shape, pick the
                  next token, expiry, the pool config, the child environment
- ports.py        what the use case needs from the world
- adapters.py     KeePass, the state file, the CLI health check, the raw-output log
- application.py  run_routine: the bounded failover loop
- fixtures.py     recorded (exit code, stdout, stderr) triples the classifier is written
                  against, each marked verified or not

Runbook: 30-Knowledge/2026-09-15-runbook-brain-routine-auth.md
"""
