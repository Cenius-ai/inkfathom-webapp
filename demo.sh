#!/usr/bin/env bash
# InkFathom end-to-end demo.
#
# Non-interactive by design: every command carries --passphrase so nothing waits
# on a hidden prompt, nothing touches the network, and the whole run exits 0.
# It writes to a throwaway ledger at .inkfathom-demo/ledger.json so your real
# ~/.inkfathom/ledger.json is never touched.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
PASS="cenius"
DEMO_DIR="$PWD/.inkfathom-demo"
LEDGER="$DEMO_DIR/ledger.json"

rm -rf "$DEMO_DIR"

step() { printf '\n\033[38;2;30;144;99m── %s ──────────────────────────────\033[0m\n' "$*"; }
run() { "$PYTHON" inkfathom.py --ledger "$LEDGER" --passphrase "$PASS" "$@"; }
expected_failure() {
  local code=0
  set +e
  "$PYTHON" inkfathom.py --ledger "$LEDGER" --passphrase "$PASS" "$@" 2>&1
  code=$?
  set -e
  printf '  (exit %s, refused as expected)\n' "$code"
}

step "InkFathom $( "$PYTHON" inkfathom.py --version | cut -d' ' -f2 )"
"$PYTHON" inkfathom.py --version
printf 'Demo ledger: %s\n' "$LEDGER"

step "1. First run: set the passphrase (stored as a salted PBKDF2 hash)"
run auth setup
printf 'passphrase used in this demo: %s\n' "$PASS"
"$PYTHON" inkfathom.py --ledger "$LEDGER" --passphrase "$PASS" auth check

step "2. Patch tests for three clients"
run patchtest add --client "Ada Reyes" --date 2024-04-20 --outcome fail
run patchtest add --client "Ada Reyes" --date 2024-04-28 --outcome pass
run patchtest add --client "Marcus Bell" --date 2024-04-11 --outcome fail
run patchtest add --client "Ines Duarte" --date 2024-03-30 --outcome pass

step "3. Log sessions (Marcus Bell's latest patch test failed, so it warns)"
run session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 2.5
run session add --client "Marcus Bell" --date 2024-05-09 --ink-ml 1.25
run session add --client "Ines Duarte" --date 2024-05-14 --ink-ml 0.75
run session add --client "Ada Reyes" --date 2024-05-21 --ink-ml 3.125

step "4. The session ledger, newest first"
run session list

step "5. Record needle use by session id and by client + date"
ADA_SESSION="$( "$PYTHON" inkfathom.py --ledger "$LEDGER" --passphrase "$PASS" \
  session list --json | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["sessions"][0]["id"])' )"
printf 'using session %s (the newest one)\n' "$ADA_SESSION"
run needle add --session-id "$ADA_SESSION" --gauge 0.30mm --quantity 3
run needle add --client "Marcus Bell" --date 2024-05-09 --gauge 0.25mm
run needle add --client "Marcus Bell" --date 2024-05-09 --gauge 0.25mm --quantity 2
run needle add --client "Ines Duarte" --date 2024-05-14 --gauge 1.20mm

step "6. Needle tally by client and gauge"
run needle list
run needle list --client "Marcus Bell"

step "7. Patch test history, latest marked"
run patchtest list --client "Ada Reyes"
run patchtest list --client "Marcus Bell"

step "8. Refusals (exit 2, one line, ledger unchanged)"
expected_failure session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 0
expected_failure needle add --session-id "$ADA_SESSION" --gauge 30g
expected_failure patchtest add --client "Ada Reyes" --date 2024-04-20 --outcome maybe
expected_failure needle add --client "Zed" --date 2024-06-01 --gauge 0.30mm

step "9. Wrong passphrase is refused once, with no detail"
expected_failure_wrong() {
  local code=0
  set +e
  "$PYTHON" inkfathom.py --ledger "$LEDGER" --passphrase "not-my-passphrase" session list 2>&1
  code=$?
  set -e
  printf '  (exit %s)\n' "$code"
}
expected_failure_wrong

step "Done - the ledger is human-readable JSON"
printf 'sessions: %s  needle uses: %s  patch tests: %s\n' \
  "$( "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["sessions"]))' "$LEDGER" )" \
  "$( "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["needle_uses"]))' "$LEDGER" )" \
  "$( "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["patch_tests"]))' "$LEDGER" )"
printf 'Try it yourself:\n'
printf '  python3 inkfathom.py session list --ledger %s --passphrase %s\n' "$LEDGER" "$PASS"
printf '  python3 inkfathom.py --help\n'
