# Installing InkFathom

InkFathom is a single Python file that uses the standard library only. There is
**no package manager step, no lockfile and no third-party dependency** — nothing is
downloaded at install time and nothing is downloaded at run time.

## 1. Prerequisite: a Python interpreter

| Requirement | Version | Notes |
| --- | --- | --- |
| Python | 3.8 or newer | `python3 --version` must print 3.8+ |

No other system package is needed: no compiler, no database driver, no sqlite
library, no network access.

## 2. Install (verifies the interpreter, then exits)

```bash
bash install.sh
```

The script:

1. prints the interpreter version and fails if it is older than 3.8;
2. parses `inkfathom.py` with `ast.parse` so a truncated download fails loudly here
   instead of at boot;
3. reports how many dependencies are declared (`requirements.txt` is intentionally
   empty);
4. prints `inkfathom 1.0.0` and **exits 0** — it never starts anything in the
   foreground.

It is safe to re-run at any time.

If you prefer to skip it: there is nothing to install, `python3 inkfathom.py --help`
is the whole setup.

## 3. Seed demo data (its own step, before running)

InkFathom's demo is non-interactive and writes to a throwaway ledger, so it never
touches `~/.inkfathom/ledger.json`:

```bash
bash demo.sh
```

That creates `.inkfathom-demo/ledger.json` with four sessions, four needle uses and
four patch tests for three clients, using the demo passphrase `cenius`, and exercises
the passphrase gate, the warning path and the refusal paths. Delete
`.inkfathom-demo/` to reset it — the script does that for you every run.

## 4. Run it

```bash
python3 inkfathom.py --help
```

First run against a fresh ledger:

```bash
python3 inkfathom.py auth setup          # asks once: "Set a passphrase:"
python3 inkfathom.py session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 2.5
python3 inkfathom.py session list        # asks: "Passphrase:"
```

Scripted / non-interactive use passes `--passphrase` instead of the hidden prompt.
With no TTY on stdin and no `--passphrase`, InkFathom refuses with exit 1 rather than
hanging.

## 5. Verify

```bash
python3 -m unittest test_inkfathom -v
```

The suite drives the real CLI as a subprocess against throwaway ledgers. One test is
skipped when the suite runs as root (a read-only directory is still writable for
root); everything else must pass.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `INKFATHOM_LEDGER` | `~/.inkfathom/ledger.json` | ledger path; `--ledger PATH` wins over it |
| `NO_COLOR` / `INKFATHOM_NO_COLOR` | unset | disable the accent colour (always off when stdout is not a TTY) |

There are no secrets to configure: the passphrase lives only in your head and as a
salted PBKDF2 hash inside the ledger file.
