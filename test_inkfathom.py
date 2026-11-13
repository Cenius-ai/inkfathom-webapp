"""Regression suite for inkfathom.py.

Runs under the standard library runner and under pytest:

    python -m unittest test_inkfathom -v
    python -m pytest test_inkfathom.py -q

Every test drives the real CLI as a subprocess against a throwaway ledger, so the
tests assert the shipped contract (exit codes, streams, file contents).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
CLI = PROJECT_ROOT / "inkfathom.py"
PASSPHRASE = "cenius"
SESSION_ID = re.compile(r"\bS-[0-9a-f]{6}\b")
NEEDLE_ID = re.compile(r"\bN-[0-9a-f]{6}\b")
PATCH_ID = re.compile(r"\bP-[0-9a-f]{6}\b")

EMPTY_SESSIONS = (
    "No sessions yet — add one with: "
    "inkfathom session add --client NAME --date YYYY-MM-DD --ink-ml N"
)
EMPTY_NEEDLES_CLIENT = (
    "No needles recorded for that client yet — add one with: "
    "inkfathom needle add --session-id ID --gauge 0.30mm"
)
EMPTY_PATCH_TESTS = (
    "No patch tests recorded for that client yet — add one with: "
    "inkfathom patchtest add --client NAME --date YYYY-MM-DD --outcome pass|fail"
)
NO_LEDGER = object()


class LedgerTestCase(unittest.TestCase):
    """Shared harness: a temp ledger plus helpers that run the CLI."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.ledger = self.tmp / "ledger.json"

    def cli(self, *args, passphrase=PASSPHRASE, ledger=None, env=None, use_ledger=True):
        argv = [sys.executable, str(CLI)]
        if use_ledger:
            target = self.ledger if ledger is None else ledger
            argv += ["--ledger", str(target)]
        if passphrase is not None:
            argv += ["--passphrase", passphrase]
        argv += [str(argument) for argument in args]
        environment = {key: value for key, value in os.environ.items()
                       if key != "INKFATHOM_LEDGER"}
        environment["NO_COLOR"] = "1"
        if env:
            environment.update(env)
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=environment,
            cwd=str(PROJECT_ROOT),
            timeout=60,
        )

    def run_ok(self, *args, **kwargs) -> subprocess.CompletedProcess:
        result = self.cli(*args, **kwargs)
        self.assertEqual(
            result.returncode, 0,
            msg=f"expected success, got {result.returncode}: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        return result

    def run_fail(self, expected_code: int, *args, **kwargs) -> subprocess.CompletedProcess:
        result = self.cli(*args, **kwargs)
        self.assertEqual(
            result.returncode, expected_code,
            msg=f"expected exit {expected_code}, got {result.returncode}: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, msg=f"expected exactly one stderr line, got {lines!r}")
        self.assertEqual(result.stdout.strip(), "", msg="failures must not write to stdout")
        return result

    def ledger_data(self) -> dict:
        return json.loads(self.ledger.read_text(encoding="utf-8"))

    def ledger_bytes(self) -> bytes:
        return self.ledger.read_bytes()

    def add_session(self, client="Ada Reyes", date="2024-05-02", ink_ml="2.5") -> str:
        result = self.run_ok("session", "add", "--client", client, "--date", date,
                             "--ink-ml", ink_ml)
        match = SESSION_ID.search(result.stdout)
        self.assertIsNotNone(match, msg=f"no session id in {result.stdout!r}")
        return match.group(0)

    def add_patch_test(self, client="Ada Reyes", date="2024-04-20", outcome="pass") -> str:
        result = self.run_ok("patchtest", "add", "--client", client, "--date", date,
                             "--outcome", outcome)
        match = PATCH_ID.search(result.stdout)
        self.assertIsNotNone(match, msg=f"no patch test id in {result.stdout!r}")
        return match.group(0)


class SessionLedgerTests(LedgerTestCase):
    def test_empty_list_points_at_the_add_command(self):
        result = self.run_ok("session", "list")
        self.assertEqual(result.stdout.strip(), EMPTY_SESSIONS)

    def test_add_echoes_an_id_and_list_shows_the_row(self):
        session_id = self.add_session()
        self.assertRegex(session_id, r"^S-[0-9a-f]{6}$")
        listing = self.run_ok("session", "list").stdout
        self.assertIn(session_id, listing)
        self.assertIn("Ada Reyes", listing)
        self.assertIn("2024-05-02", listing)
        self.assertIn("2.50 ml", listing)

    def test_three_sessions_get_distinct_ids_and_newest_is_first(self):
        first = self.add_session(date="2024-05-01")
        second = self.add_session(date="2024-05-02")
        third = self.add_session(date="2024-05-03")
        self.assertEqual(len({first, second, third}), 3)
        rows = [line for line in self.run_ok("session", "list").stdout.splitlines()
                if SESSION_ID.search(line)]
        self.assertEqual([SESSION_ID.search(row).group(0) for row in rows],
                         [third, second, first])

    def test_most_recently_added_wins_on_the_same_date(self):
        first = self.add_session(date="2024-05-02")
        second = self.add_session(date="2024-05-02")
        rows = [line for line in self.run_ok("session", "list").stdout.splitlines()
                if SESSION_ID.search(line)]
        self.assertEqual([SESSION_ID.search(row).group(0) for row in rows], [second, first])

    def test_ink_volume_is_stored_as_a_decimal_string(self):
        self.add_session(ink_ml="0.125")
        stored = self.ledger_data()["sessions"][0]
        self.assertEqual(stored["ink_ml"], "0.125")
        self.assertIsInstance(stored["ink_ml"], str)

    def test_validation_failures_exit_two_and_change_nothing(self):
        for _ in range(3):
            self.add_session()
        before = self.ledger_bytes()
        cases = [
            (("session", "add", "--client", "Ada Reyes", "--date", "2024-05-02",
              "--ink-ml", "0"), "--ink-ml"),
            (("session", "add", "--client", "Ada Reyes", "--date", "2024-05-02",
              "--ink-ml", "abc"), "--ink-ml"),
            (("session", "add", "--client", "Ada Reyes", "--date", "2024-05-02",
              "--ink-ml", "2.5000"), "--ink-ml"),
            (("session", "add", "--client", "Ada Reyes", "--date", "2024-13-40",
              "--ink-ml", "2.5"), "--date"),
            (("session", "add", "--client", "   ", "--date", "2024-05-02",
              "--ink-ml", "2.5"), "--client"),
            (("session", "add",), "--client"),
        ]
        for arguments, field in cases:
            with self.subTest(arguments=arguments):
                result = self.run_fail(2, *arguments)
                self.assertIn(field, result.stderr)
                self.assertEqual(self.ledger_bytes(), before)

    def test_no_temp_file_survives_a_successful_write(self):
        self.add_session()
        self.assertEqual(len(self.ledger_data()["sessions"]), 1)
        names = sorted(entry.name for entry in self.tmp.iterdir())
        self.assertEqual(names, ["ledger.json"])

    def test_failed_write_leaves_the_ledger_byte_identical(self):
        for _ in range(3):
            self.add_session()
        before = self.ledger_bytes()
        blocker = self.tmp / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        result = self.run_fail(
            1, "session", "add", "--client", "Ada Reyes", "--date", "2024-05-04",
            "--ink-ml", "1.5", ledger=blocker / "ledger.json",
        )
        self.assertIn("Cannot write ledger", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(len(self.ledger_data()["sessions"]), 3)

    def test_read_only_ledger_directory_is_reported_not_crashed(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("running as root: a read-only directory is still writable")
        self.add_session()
        before = self.ledger_bytes()
        os.chmod(self.tmp, 0o500)
        self.addCleanup(os.chmod, self.tmp, 0o700)
        result = self.run_fail(
            1, "session", "add", "--client", "Ada Reyes", "--date", "2024-05-04",
            "--ink-ml", "1.5",
        )
        self.assertIn("Cannot write ledger", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_malformed_ledger_is_one_line_and_left_alone(self):
        self.ledger.write_text("{not json", encoding="utf-8")
        result = self.run_fail(1, "session", "list")
        self.assertIn("not valid JSON", result.stderr)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), "{not json")

    def test_json_output_is_machine_readable(self):
        session_id = self.add_session()
        payload = json.loads(self.run_ok("session", "list", "--json").stdout)
        self.assertEqual(payload["sessions"][0]["id"], session_id)
        self.assertEqual(payload["sessions"][0]["ink_ml"], "2.500")

    def test_ledger_path_can_come_from_the_environment(self):
        self.run_ok("session", "add", "--client", "Ada Reyes", "--date", "2024-05-02",
                    "--ink-ml", "2.5", use_ledger=False,
                    env={"INKFATHOM_LEDGER": str(self.ledger)})
        self.assertTrue(self.ledger.exists())
        listing = self.run_ok("session", "list", use_ledger=False,
                              env={"INKFATHOM_LEDGER": str(self.ledger)}).stdout
        self.assertIn("Ada Reyes", listing)


class PassphraseTests(LedgerTestCase):
    def test_first_command_stores_only_a_salted_hash(self):
        self.add_session()
        ledger = self.ledger_data()
        self.assertIn("kdf", ledger)
        self.assertGreaterEqual(ledger["kdf"]["iterations"], 100000)
        self.assertEqual(len(ledger["kdf"]["salt_hex"]), 32)
        self.assertEqual(len(ledger["kdf"]["hash_hex"]), 64)
        self.assertNotIn(PASSPHRASE, self.ledger.read_text(encoding="utf-8"))

    def test_correct_passphrase_runs_the_command(self):
        self.add_session()
        result = self.run_ok("session", "list")
        self.assertIn("Ada Reyes", result.stdout)

    def test_wrong_passphrase_is_one_line_and_leaves_the_ledger(self):
        self.add_session()
        before = self.ledger_bytes()
        result = self.run_fail(1, "session", "list", passphrase="wrong-one")
        self.assertEqual(result.stderr.strip(), "Passphrase not recognised.")
        self.assertEqual(self.ledger_bytes(), before)

    def test_passphrase_is_required_when_stdin_is_not_a_terminal(self):
        self.add_session()
        before = self.ledger_bytes()
        result = self.run_fail(1, "session", "list", passphrase=None)
        self.assertIn("--passphrase", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_auth_check_accepts_the_right_passphrase(self):
        self.add_session()
        self.assertEqual(self.run_ok("auth", "check").stdout.strip(), "Passphrase accepted.")

    def test_auth_check_rejects_the_wrong_passphrase(self):
        self.add_session()
        result = self.run_fail(1, "auth", "check", passphrase="nope")
        self.assertEqual(result.stderr.strip(), "Passphrase not recognised.")

    def test_auth_setup_is_safe_to_run_twice(self):
        self.run_ok("auth", "setup")
        result = self.run_ok("auth", "setup")
        self.assertIn("already set", result.stdout)
        self.assertEqual(self.run_ok("session", "list").stdout.strip(), EMPTY_SESSIONS)

    def test_passphrase_flag_works_after_the_subcommand(self):
        self.add_session()
        result = self.cli("session", "list", "--passphrase", PASSPHRASE)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Ada Reyes", result.stdout)

    def test_empty_passphrase_is_rejected(self):
        result = self.run_fail(2, "session", "list", passphrase="")
        self.assertIn("Passphrase must not be empty.", result.stderr)
        self.assertFalse(self.ledger.exists())


class NeedleTests(LedgerTestCase):
    def test_add_by_session_id_stores_the_link(self):
        session_id = self.add_session()
        result = self.run_ok("needle", "add", "--session-id", session_id,
                             "--gauge", "0.30mm", "--quantity", "3")
        needle_id = NEEDLE_ID.search(result.stdout).group(0)
        self.assertRegex(needle_id, r"^N-[0-9a-f]{6}$")
        use = self.ledger_data()["needle_uses"][0]
        self.assertEqual(use["session_id"], session_id)
        self.assertEqual(use["gauge"], "0.30mm")
        self.assertEqual(use["quantity"], 3)
        self.assertEqual(use["client"], "Ada Reyes")

    def test_unique_client_and_date_resolve_the_session(self):
        session_id = self.add_session()
        self.run_ok("needle", "add", "--client", "Ada Reyes",
                    "--date", "2024-05-02", "--gauge", "0.25mm")
        use = self.ledger_data()["needle_uses"][0]
        self.assertEqual(use["session_id"], session_id)
        self.assertEqual(use["quantity"], 1)
        tally = self.run_ok("needle", "list", "--client", "Ada Reyes").stdout
        self.assertIn("0.25mm  1", tally)

    def test_tally_sums_quantities_per_gauge(self):
        session_id = self.add_session()
        self.run_ok("needle", "add", "--session-id", session_id, "--gauge", "0.25mm")
        self.run_ok("needle", "add", "--session-id", session_id, "--gauge", "0.25mm",
                    "--quantity", "2")
        self.run_ok("needle", "add", "--session-id", session_id, "--gauge", "0.30mm",
                    "--quantity", "2")
        tally = self.run_ok("needle", "list", "--client", "Ada Reyes").stdout
        self.assertIn("0.25mm  3", tally)
        self.assertIn("0.30mm  2", tally)
        self.assertIn("total   5", tally)

    def test_no_matching_session_is_refused(self):
        self.add_session()
        before = self.ledger_bytes()
        result = self.run_fail(2, "needle", "add", "--client", "Zed",
                               "--date", "2024-06-01", "--gauge", "0.30mm")
        self.assertIn("No session found", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_ambiguous_session_lists_both_candidates(self):
        first = self.add_session(date="2024-05-02", ink_ml="1")
        second = self.add_session(date="2024-05-02", ink_ml="1.5")
        before = self.ledger_bytes()
        result = self.run_fail(2, "needle", "add", "--client", "Ada Reyes",
                               "--date", "2024-05-02", "--gauge", "0.30mm")
        self.assertIn("ambiguous", result.stderr.lower())
        self.assertIn(first, result.stderr)
        self.assertIn(second, result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_unknown_session_id_is_refused(self):
        self.add_session()
        before = self.ledger_bytes()
        result = self.run_fail(2, "needle", "add", "--session-id", "S-000000",
                               "--gauge", "0.30mm")
        self.assertIn("S-000000", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_out_of_set_gauge_labels_are_rejected(self):
        session_id = self.add_session()
        before = self.ledger_bytes()
        for bad_gauge in ("30g", "0.3", "0.15mm", "2.01mm", "0,30mm", "mm"):
            with self.subTest(gauge=bad_gauge):
                result = self.run_fail(2, "needle", "add", "--session-id", session_id,
                                       "--gauge", bad_gauge)
                self.assertIn("0.30mm", result.stderr)
                self.assertEqual(self.ledger_bytes(), before)

    def test_accepted_gauge_boundaries(self):
        session_id = self.add_session()
        for gauge in ("0.16mm", "2.00mm", "1.20mm"):
            with self.subTest(gauge=gauge):
                self.run_ok("needle", "add", "--session-id", session_id, "--gauge", gauge)
        self.assertEqual(len(self.ledger_data()["needle_uses"]), 3)

    def test_quantity_must_be_a_positive_whole_number(self):
        session_id = self.add_session()
        before = self.ledger_bytes()
        for bad_quantity in ("0", "-2", "1.5", "many", "10001"):
            with self.subTest(quantity=bad_quantity):
                result = self.run_fail(2, "needle", "add", "--session-id", session_id,
                                       "--gauge", "0.30mm", "--quantity", bad_quantity)
                self.assertIn("--quantity", result.stderr)
                self.assertEqual(self.ledger_bytes(), before)

    def test_empty_state_for_an_untallied_client(self):
        self.add_session()
        result = self.run_ok("needle", "list", "--client", "Zed")
        self.assertEqual(result.stdout.strip(), EMPTY_NEEDLES_CLIENT)

    def test_needle_group_without_a_subcommand_asks_for_one(self):
        self.add_session()
        result = self.run_fail(2, "needle")
        self.assertIn("--help", result.stderr)


class PatchTestTests(LedgerTestCase):
    def test_add_echoes_an_id_and_list_shows_it(self):
        patch_id = self.add_patch_test(date="2024-04-20", outcome="pass")
        self.assertRegex(patch_id, r"^P-[0-9a-f]{6}$")
        listing = self.run_ok("patchtest", "list", "--client", "Ada Reyes").stdout
        self.assertIn("2024-04-20", listing)
        self.assertIn("pass", listing)
        self.assertIn("latest", listing)

    def test_most_recent_record_is_marked_latest(self):
        self.add_patch_test(date="2024-04-20", outcome="fail")
        self.add_patch_test(date="2024-04-28", outcome="pass")
        rows = [line for line in
                self.run_ok("patchtest", "list", "--client", "Ada Reyes").stdout.splitlines()
                if "2024-" in line]
        self.assertEqual(len(rows), 2)
        self.assertIn("2024-04-28", rows[0])
        self.assertTrue(rows[0].startswith("latest"))
        self.assertFalse(rows[1].startswith("latest"))

    def test_only_the_named_client_is_listed(self):
        self.add_patch_test(client="Ada Reyes", date="2024-04-20", outcome="fail")
        self.add_patch_test(client="Marcus Bell", date="2024-04-22", outcome="pass")
        listing = self.run_ok("patchtest", "list", "--client", "Marcus Bell").stdout
        self.assertIn("2024-04-22", listing)
        self.assertNotIn("2024-04-20", listing)

    def test_invalid_outcome_is_rejected(self):
        self.add_session()
        before = self.ledger_bytes()
        result = self.run_fail(2, "patchtest", "add", "--client", "Ada Reyes",
                               "--date", "2024-04-20", "--outcome", "maybe")
        self.assertIn("pass or fail", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_malformed_patch_test_date_is_rejected(self):
        self.add_session()
        before = self.ledger_bytes()
        result = self.run_fail(2, "patchtest", "add", "--client", "Ada Reyes",
                               "--date", "2024-02-31", "--outcome", "pass")
        self.assertIn("--date", result.stderr)
        self.assertEqual(self.ledger_bytes(), before)

    def test_empty_state_for_an_untested_client(self):
        self.add_session()
        result = self.run_ok("patchtest", "list", "--client", "Zed")
        self.assertEqual(result.stdout.strip(), EMPTY_PATCH_TESTS)


class PatchTestWarningTests(LedgerTestCase):
    def test_failed_latest_patch_test_warns_on_session_add(self):
        self.add_patch_test(date="2024-04-20", outcome="fail")
        result = self.run_ok("session", "add", "--client", "Ada Reyes",
                             "--date", "2024-05-02", "--ink-ml", "2.5")
        self.assertIn(
            "WARNING: most recent patch test for Ada Reyes (2024-04-20) FAILED",
            result.stdout,
        )
        self.assertRegex(result.stdout, r"S-[0-9a-f]{6}")
        self.assertEqual(len(self.ledger_data()["sessions"]), 1)

    def test_later_pass_suppresses_the_warning(self):
        self.add_patch_test(date="2024-04-20", outcome="fail")
        self.add_patch_test(date="2024-04-28", outcome="pass")
        result = self.run_ok("session", "add", "--client", "Ada Reyes",
                             "--date", "2024-05-02", "--ink-ml", "2.5")
        self.assertNotIn("WARNING", result.stdout)
        self.assertEqual(len(self.ledger_data()["sessions"]), 1)

    def test_an_old_failure_still_warns(self):
        self.add_patch_test(date="2023-01-05", outcome="fail")
        result = self.run_ok("session", "add", "--client", "Ada Reyes",
                             "--date", "2024-05-02", "--ink-ml", "2.5")
        self.assertIn("(2023-01-05) FAILED", result.stdout)

    def test_no_patch_test_means_no_warning(self):
        result = self.run_ok("session", "add", "--client", "Zed",
                             "--date", "2024-05-02", "--ink-ml", "2.5")
        self.assertNotIn("WARNING", result.stdout)

    def test_another_clients_failure_does_not_warn(self):
        self.add_patch_test(client="Marcus Bell", date="2024-04-20", outcome="fail")
        result = self.run_ok("session", "add", "--client", "Ada Reyes",
                             "--date", "2024-05-02", "--ink-ml", "2.5")
        self.assertNotIn("WARNING", result.stdout)


class CommandLineTests(LedgerTestCase):
    def test_help_lists_every_command_group_with_an_example(self):
        result = self.run_ok("--help")
        for expected in ("session", "needle", "patchtest", "auth",
                         "inkfathom session add --client", "inkfathom needle add",
                         "inkfathom patchtest add"):
            self.assertIn(expected, result.stdout)

    def test_subcommand_help_is_available(self):
        for group in ("session", "needle", "patchtest", "auth"):
            with self.subTest(group=group):
                result = self.run_ok(group, "--help")
                self.assertIn("usage: inkfathom", result.stdout)

    def test_unknown_command_is_a_single_line_pointing_at_help(self):
        result = self.run_fail(2, "frobnicate")
        self.assertIn("Unknown command", result.stderr)
        self.assertIn("--help", result.stderr)

    def test_missing_subcommand_is_a_single_line(self):
        result = self.run_fail(2, "session")
        self.assertIn("--help", result.stderr)

    def test_version_is_printed(self):
        result = self.run_ok("--version")
        self.assertIn("inkfathom", result.stdout)

    def test_bare_invocation_prints_help_and_exits_zero(self):
        result = self.run_ok()
        self.assertIn("usage: inkfathom", result.stdout)
        self.assertIn("ledger:", result.stdout)

    def test_ledger_flag_wins_over_the_environment_variable(self):
        self.add_session()
        other = self.tmp / "other.json"
        listing = self.run_ok("session", "list", ledger=other,
                              env={"INKFATHOM_LEDGER": str(self.ledger)}).stdout
        self.assertEqual(listing.strip(), EMPTY_SESSIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
