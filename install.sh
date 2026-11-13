#!/usr/bin/env bash
# InkFathom setup: there is nothing to install (standard library only).
# This script verifies the interpreter, checks the source parses, and exits 0.
# Start the tool itself with: python3 inkfathom.py --help
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

printf 'InkFathom setup\n'
printf 'Python: %s\n' "$( "$PYTHON" -c 'import sys; print(sys.version.split()[0])' )"

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else "InkFathom needs Python 3.8 or newer")'

# Cheap self-check: the shipped source must parse under this interpreter.
"$PYTHON" -c 'import ast, pathlib; ast.parse(pathlib.Path("inkfathom.py").read_text(encoding="utf-8")); print("inkfathom.py parses cleanly")'

# No third-party dependencies: requirements.txt is intentionally empty.
if [ -f requirements.txt ]; then
  printf 'Dependencies declared: %s\n' "$( grep -cv '^\s*\(#.*\)\?$' requirements.txt || true )"
fi

"$PYTHON" inkfathom.py --version

printf '\nSetup complete. Nothing was installed and no ledger was created.\n'
printf 'Next:\n'
printf '  python3 inkfathom.py --help      # command list and examples\n'
printf '  bash demo.sh                     # full non-interactive demo\n'
printf '  python3 -m unittest test_inkfathom -v\n'
