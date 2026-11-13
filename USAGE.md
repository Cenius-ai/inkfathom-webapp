# Using InkFathom

Every command is gated by the ledger passphrase: InkFathom prompts for it (hidden
input) unless you pass `--passphrase`. `--ledger PATH` and `--passphrase` are accepted
before *or* after the subcommand.

```bash
alias ink="python3 inkfathom.py"
```

## Sessions — ink volume per session

```bash
ink session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 2.5
# Added session S-c59836 — Ada Reyes, 2024-05-02, 2.50 ml

ink session add --client "Marcus Bell" --date 2024-05-09 --ink-ml 1.25
# Added session S-7f515a — Marcus Bell, 2024-05-09, 1.25 ml
# WARNING: most recent patch test for Marcus Bell (2024-04-11) FAILED

ink session list
# ID          CLIENT       DATE        INK
# ──────────────────────────────────────────────
# S-7f515a    Marcus Bell  2024-05-09    1.25 ml
# S-c59836    Ada Reyes    2024-05-02    2.50 ml
# ──────────────────────────────────────────────
# 2 sessions · newest first

ink session list --json          # stable structured output for scripting
```

* The id is generated (`S-` plus six lowercase hex characters) and printed on add.
* `--ink-ml` must be greater than 0, at most 500, with at most 3 decimal places. It is
  stored as a decimal string (never a float) and rendered with 2 decimals, rounding
  half to even.
* `--date` must be a real calendar date written `YYYY-MM-DD`.
* `--client` is trimmed and must be 1–80 characters.
* Ordering is newest date first; two sessions on the same date fall back to the most
  recently added.

Empty ledger:

```
No sessions yet — add one with: inkfathom session add --client NAME --date YYYY-MM-DD --ink-ml N
```

## Needles — gauge consumption per client

```bash
ink needle add --session-id S-c59836 --gauge 0.30mm --quantity 3
# Added needle use N-bb45f8 — Ada Reyes, S-c59836, 0.30mm ×3

ink needle add --client "Ada Reyes" --date 2024-05-02 --gauge 0.25mm
# Added needle use N-75f95d — Ada Reyes, S-c59836, 0.25mm ×1   (--quantity defaults to 1)

ink needle list --client "Ada Reyes"
# Ada Reyes
# ────────────────
# 0.25mm  1
# 0.30mm  3
# total   4
```

* A gauge is a decimal millimetre value with exactly two decimals and an `mm` suffix,
  between `0.16mm` and `2.00mm` inclusive. `30g`, `0.3`, `0,30mm` and `2.01mm` are all
  refused.
* `--quantity` is a positive whole number (default 1).
* Session resolution: `--session-id`, or `--client` + `--date` when **exactly one**
  session matches. Zero matches is an error naming the add command; more than one match
  is an error listing the candidate ids so you can pass `--session-id`.
* `ink needle list` with no `--client` tallies every client, one block each.

Untallied client:

```
No needles recorded for that client yet — add one with: inkfathom needle add --session-id ID --gauge 0.30mm
```

## Patch tests

```bash
ink patchtest add --client "Ada Reyes" --date 2024-04-20 --outcome fail
# Added patch test P-22f554 — Ada Reyes, 2024-04-20, fail

ink patchtest add --client "Ada Reyes" --date 2024-04-28 --outcome pass
ink patchtest list --client "Ada Reyes"
# Ada Reyes · patch tests, newest first
# MARK    DATE        OUTCOME
# ───────────────────────────
# latest  2024-04-28  pass
#         2024-04-20  fail
# ───────────────────────────
```

* `--outcome` is `pass` or `fail` (case-insensitive, stored lowercase). Anything else
  is refused with exit 2.
* The newest record **by date** is marked `latest` and is the only one that decides the
  warning on `session add`. There is no recency cutoff: a failed test from last year
  still warns until a later test passes.

Untested client:

```
No patch tests recorded for that client yet — add one with: inkfathom patchtest add --client NAME --date YYYY-MM-DD --outcome pass|fail
```

## The passphrase gate

```bash
ink auth setup            # first run: "Set a passphrase:" (hidden, no echo)
ink auth check            # verify only: prints "Passphrase accepted." or exits 1
ink session list --passphrase cenius    # scripted runs
```

* Only a 16-byte salt, the iteration count (200 000) and the PBKDF2-HMAC-SHA256 hash
  are stored. The plaintext passphrase never appears in the ledger, in stdout/stderr,
  or in an error message.
* A wrong passphrase prints exactly one line — `Passphrase not recognised.` — and exits
  1 with the ledger untouched. It never says which part was wrong.
* `auth setup` on a ledger that already has a passphrase verifies it and reports that
  nothing changed, so it is safe to re-run.

## Exit codes and streams

| Code | Meaning |
| --- | --- |
| 0 | success (including empty states) |
| 1 | passphrase failure, ledger read/write failure, I/O |
| 2 | validation failure or bad command line |

Results — including the patch-test `WARNING:` line, which is product output — go to
**stdout**. Errors and notices go to **stderr**, exactly one line per failure. So
`inkfathom session list | grep '^S-'` stays clean and `2>/dev/null` hides only
diagnostics.

## Exit-code examples

```bash
ink session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 0
# stderr: --ink-ml must be a number of millilitres greater than 0 and at most 500, ...
# exit 2, ledger unchanged

ink needle add --session-id S-c59836 --gauge 30g
# stderr: --gauge must be a decimal millimetre value such as 0.30mm (from 0.16mm to 2.00mm inclusive).
# exit 2, ledger unchanged

ink frobnicate
# stderr: Unknown command 'frobnicate' — run 'inkfathom --help' for the command list.
# exit 2
```

## Hand-editing the ledger

The file is pretty-printed JSON:

```json
{
  "version": 1,
  "sessions": [
    { "id": "S-c59836", "client": "Ada Reyes", "date": "2024-05-02",
      "ink_ml": "2.500", "created_at": "2024-05-02T09:14:03.812345+00:00" }
  ],
  "needle_uses": [],
  "patch_tests": [],
  "kdf": { "algorithm": "pbkdf2_hmac_sha256", "salt_hex": "…",
           "iterations": 200000, "hash_hex": "…" }
}
```

Edit it between runs if you need to fix a typo; InkFathom validates the shape on read
and refuses (exit 1, one line) rather than overwriting a file it cannot parse.
