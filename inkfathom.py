#!/usr/bin/env python3
"""InkFathom - a tattoo artist's session, ink, needle and patch-test ledger.

One file, standard library only. The whole ledger is a single pretty-printed
JSON document (default ~/.inkfathom/ledger.json) that a curious operator can
read and hand-edit between runs.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile

VERSION = "1.0.0"
LEDGER_VERSION = 1
PBKDF2_ITERATIONS = 200000
MAX_CLIENT_LENGTH = 80
MAX_INK_THOUSANDTHS = 500000  # 500.000 ml per session
MAX_NEEDLE_QUANTITY = 10000
DEFAULT_LEDGER_PATH = "~/.inkfathom/ledger.json"

# --- design tokens (committed direction: calm-precise, terminal dark) --------
# Accent: oklch(0.58 0.12 161) == #1e9063, used for the single primary signal.
ACCENT_HEX = "#1e9063"
ACCENT_OKLCH = "oklch(0.58 0.12 161)"
ACCENT_ANSI = "\x1b[38;2;30;144;99m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
RULE = "─"
ELLIPSIS = "…"

EMPTY_SESSIONS = (
    "No sessions yet — add one with: "
    "inkfathom session add --client NAME --date YYYY-MM-DD --ink-ml N"
)
EMPTY_NEEDLES_CLIENT = (
    "No needles recorded for that client yet — add one with: "
    "inkfathom needle add --session-id ID --gauge 0.30mm"
)
EMPTY_NEEDLES_ALL = (
    "No needle uses recorded yet — add one with: "
    "inkfathom needle add --session-id ID --gauge 0.30mm"
)
EMPTY_PATCH_TESTS = (
    "No patch tests recorded for that client yet — add one with: "
    "inkfathom patchtest add --client NAME --date YYYY-MM-DD --outcome pass|fail"
)

DATE_HELP = "--date must be a calendar date written as YYYY-MM-DD."
INK_HELP = (
    "--ink-ml must be a number of millilitres greater than 0 and at most 500, "
    "with no more than 3 decimal places."
)
GAUGE_HELP = (
    "--gauge must be a decimal millimetre value such as 0.30mm "
    "(from 0.16mm to 2.00mm inclusive)."
)
QUANTITY_HELP = (
    "--quantity must be a whole number of needles, 1 or more "
    f"(max {MAX_NEEDLE_QUANTITY})."
)
OUTCOME_HELP = "--outcome must be pass or fail."


# --- errors -----------------------------------------------------------------
class InkFathomError(Exception):
    """An expected, user-facing failure with a chosen exit code."""

    exit_code = 1


class ValidationError(InkFathomError):
    """Bad input from the operator (exit 2)."""

    exit_code = 2


class UsageError(InkFathomError):
    """Bad command line (exit 2)."""

    exit_code = 2


class AuthError(InkFathomError):
    """Passphrase gate failure (exit 1)."""

    exit_code = 1


class LedgerError(InkFathomError):
    """Ledger read or write failure (exit 1)."""

    exit_code = 1


class InkFathomParser(argparse.ArgumentParser):
    """Argument parser that fails with one readable stderr line, not a wall."""

    def error(self, message: str) -> None:
        if "invalid choice" in message:
            choice = message.rsplit("invalid choice:", 1)[1].split("(")[0].strip()
            raise UsageError(
                f"Unknown command {choice} — run 'inkfathom --help' "
                "for the command list."
            )
        raise UsageError(f"{message} — run 'inkfathom --help' for usage.")


# --- output helpers ---------------------------------------------------------
def colour_enabled(stream) -> bool:
    """Colour only for a real terminal, never for pipes, files or NO_COLOR."""
    if os.environ.get("NO_COLOR") or os.environ.get("INKFATHOM_NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def paint(text: str, code: str, stream=None) -> str:
    stream = sys.stdout if stream is None else stream
    return f"{code}{text}{RESET}" if colour_enabled(stream) else text


def emit_error(message: str) -> None:
    """Exactly one human-readable line on stderr."""
    print(" ".join(str(message).split()), file=sys.stderr)


def emit_notice(message: str) -> None:
    print(" ".join(str(message).split()), file=sys.stderr)


def cell(text, width: int, align: str = "left") -> str:
    text = "" if text is None else str(text)
    if len(text) > width:
        text = text[: max(width - 1, 0)] + ELLIPSIS if width > 1 else text[:width]
    return text.rjust(width) if align == "right" else text.ljust(width)


def rule(width: int) -> str:
    return paint(RULE * width, DIM)


# --- ledger persistence -----------------------------------------------------
def empty_ledger() -> dict:
    return {
        "version": LEDGER_VERSION,
        "sessions": [],
        "needle_uses": [],
        "patch_tests": [],
    }


def resolve_ledger_path(args) -> str:
    raw = getattr(args, "ledger", None)
    if raw is None:
        raw = os.environ.get("INKFATHOM_LEDGER") or DEFAULT_LEDGER_PATH
    return os.path.abspath(os.path.expanduser(raw))


def load_ledger(path: str) -> dict:
    if not os.path.exists(path):
        return empty_ledger()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise LedgerError(
            f"Cannot read ledger {path}: {exc.strerror or exc}"
        ) from None
    except json.JSONDecodeError as exc:
        raise LedgerError(
            f"Cannot read ledger {path}: not valid JSON (line {exc.lineno}). "
            "Fix the file or restore a backup."
        ) from None
    return normalise_ledger(data, path)


def normalise_ledger(data, path: str) -> dict:
    if not isinstance(data, dict):
        raise LedgerError(
            f"Cannot read ledger {path}: expected a JSON object at the top level."
        )
    version = data.get("version", LEDGER_VERSION)
    if isinstance(version, int) and version > LEDGER_VERSION:
        raise LedgerError(
            f"Cannot read ledger {path}: it was written by a newer inkfathom "
            f"(version {version}, this build understands {LEDGER_VERSION})."
        )
    ledger = empty_ledger()
    if isinstance(data.get("kdf"), dict):
        ledger["kdf"] = data["kdf"]
    for key in ("sessions", "needle_uses", "patch_tests"):
        records = data.get(key, [])
        if not isinstance(records, list) or any(
            not isinstance(record, dict) for record in records
        ):
            raise LedgerError(
                f"Cannot read ledger {path}: '{key}' must be a list of objects."
            )
        ledger[key] = records
    return ledger


def save_ledger(path: str, ledger: dict) -> None:
    """Serialise to a temp file in the ledger's directory, then swap in atomically."""
    directory = os.path.dirname(path) or "."
    payload = json.dumps(ledger, indent=2) + "\n"
    temp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        handle_fd, temp_path = tempfile.mkstemp(
            prefix=".ledger-", suffix=".tmp", dir=directory
        )
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise LedgerError(
            f"Cannot write ledger {path}: {exc.strerror or exc}. Nothing was changed."
        ) from None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# --- small validators -------------------------------------------------------
def is_ascii_digits(text: str) -> bool:
    return bool(text) and all(character in "0123456789" for character in text)


def now_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def require_client(value) -> str:
    if value is None:
        raise ValidationError("--client is required — pass the client's name.")
    client = value.strip()
    if not client:
        raise ValidationError("--client must not be blank.")
    if len(client) > MAX_CLIENT_LENGTH:
        raise ValidationError(
            f"--client must be at most {MAX_CLIENT_LENGTH} characters."
        )
    return client


def require_date(value) -> str:
    if value is None or not str(value).strip():
        raise ValidationError("--date is required — " + DATE_HELP)
    text = str(value).strip()
    parts = text.split("-")
    if len(parts) != 3 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValidationError(DATE_HELP)
    if not all(is_ascii_digits(part) for part in parts):
        raise ValidationError(DATE_HELP)
    try:
        datetime.datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(DATE_HELP) from None
    return text


def require_ink_ml(value) -> str:
    """Return the ink volume as a canonical 3-decimal string in millilitres."""
    if value is None or not str(value).strip():
        raise ValidationError(
            "--ink-ml is required — pass the ink volume in millilitres."
        )
    text = str(value).strip()
    if text.count(".") > 1 or text.endswith("."):
        raise ValidationError(INK_HELP)
    whole, _, fraction = text.partition(".")
    if not is_ascii_digits(whole) or (fraction and not is_ascii_digits(fraction)):
        raise ValidationError(INK_HELP)
    if len(fraction) > 3:
        raise ValidationError(INK_HELP)
    thousandths = int(whole) * 1000 + int((fraction + "000")[:3])
    if thousandths <= 0 or thousandths > MAX_INK_THOUSANDTHS:
        raise ValidationError(INK_HELP)
    return f"{thousandths // 1000}.{thousandths % 1000:03d}"


def to_thousandths(ink_ml: str) -> int:
    whole, _, fraction = str(ink_ml).partition(".")
    digits = (fraction + "000")[:3] or "000"
    return int(whole or "0") * 1000 + int(digits)


def display_ml(ink_ml) -> str:
    """Render a stored volume with 2 decimals, rounding half to even."""
    hundredths, remainder = divmod(to_thousandths(ink_ml), 10)
    if remainder > 5 or (remainder == 5 and hundredths % 2 == 1):
        hundredths += 1
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def require_gauge(value) -> str:
    text = str(value or "").strip()
    if not text.lower().endswith("mm"):
        raise ValidationError(GAUGE_HELP)
    body = text[:-2]
    if body.count(".") != 1:
        raise ValidationError(GAUGE_HELP)
    whole, _, fraction = body.partition(".")
    if not (1 <= len(whole) <= 2) or not is_ascii_digits(whole):
        raise ValidationError(GAUGE_HELP)
    if len(fraction) != 2 or not is_ascii_digits(fraction):
        raise ValidationError(GAUGE_HELP)
    hundredths = int(whole) * 100 + int(fraction)
    if hundredths < 16 or hundredths > 200:
        raise ValidationError(GAUGE_HELP)
    return f"{hundredths // 100}.{hundredths % 100:02d}mm"


def require_quantity(value) -> int:
    if value is None:
        return 1
    text = str(value).strip()
    if not is_ascii_digits(text) or int(text) < 1:
        raise ValidationError(QUANTITY_HELP)
    quantity = int(text)
    if quantity > MAX_NEEDLE_QUANTITY:
        raise ValidationError(QUANTITY_HELP)
    return quantity


def require_outcome(value) -> str:
    text = str(value or "").strip().lower()
    if text not in ("pass", "fail"):
        raise ValidationError(OUTCOME_HELP)
    return text


def new_id(prefix: str, taken: set) -> str:
    for _ in range(200):
        candidate = prefix + secrets.token_hex(3)
        if candidate not in taken:
            return candidate
    raise LedgerError("Could not generate a unique id — the ledger is very full.")


# --- passphrase gate --------------------------------------------------------
def hash_passphrase(passphrase: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations)


def record_passphrase(ledger: dict, passphrase: str) -> None:
    salt = secrets.token_bytes(16)
    digest = hash_passphrase(passphrase, salt, PBKDF2_ITERATIONS)
    ledger["kdf"] = {
        "algorithm": "pbkdf2_hmac_sha256",
        "salt_hex": salt.hex(),
        "iterations": PBKDF2_ITERATIONS,
        "hash_hex": digest.hex(),
    }


def verify_passphrase(ledger: dict, passphrase: str) -> bool:
    kdf = ledger.get("kdf")
    if not isinstance(kdf, dict):
        return False
    try:
        salt = bytes.fromhex(kdf["salt_hex"])
        expected = bytes.fromhex(kdf["hash_hex"])
        iterations = int(kdf["iterations"])
    except (KeyError, TypeError, ValueError):
        raise LedgerError(
            "The ledger's passphrase record is corrupt. Restore a backup, or "
            "remove the 'kdf' block to set a new passphrase."
        ) from None
    return hmac.compare_digest(hash_passphrase(passphrase, salt, iterations), expected)


def read_passphrase(args, prompt: str) -> str:
    supplied = getattr(args, "passphrase", None)
    if supplied is not None:
        return supplied
    if not sys.stdin.isatty():
        raise AuthError(
            "Passphrase required — pass --passphrase for scripted runs "
            "(stdin is not a terminal)."
        )
    return getpass.getpass(prompt)


def authenticate(args, ledger: dict, path: str, allow_setup: bool = True) -> bool:
    """Gate every command. Returns True when a new passphrase was just created."""
    if not ledger.get("kdf"):
        if not allow_setup:
            raise AuthError(
                "This ledger has no passphrase yet — run: inkfathom auth setup"
            )
        passphrase = read_passphrase(args, "Set a passphrase: ")
        if not passphrase:
            raise ValidationError("Passphrase must not be empty.")
        record_passphrase(ledger, passphrase)
        save_ledger(path, ledger)
        return True
    passphrase = read_passphrase(args, "Passphrase: ")
    if not verify_passphrase(ledger, passphrase):
        raise AuthError("Passphrase not recognised.")
    return False


# --- session commands -------------------------------------------------------
SESSION_ADD_USAGE = (
    "--client, --date and --ink-ml are required: "
    "inkfathom session add --client NAME --date YYYY-MM-DD --ink-ml N"
)


def cmd_session_add(args, ledger: dict, path: str) -> int:
    if (
        getattr(args, "client", None) is None
        and getattr(args, "date", None) is None
        and getattr(args, "ink_ml", None) is None
    ):
        raise ValidationError(SESSION_ADD_USAGE)
    client = require_client(getattr(args, "client", None))
    date = require_date(getattr(args, "date", None))
    ink_ml = require_ink_ml(getattr(args, "ink_ml", None))
    session = {
        "id": new_id("S-", {record.get("id") for record in ledger["sessions"]}),
        "client": client,
        "date": date,
        "ink_ml": ink_ml,
        "created_at": now_stamp(),
    }
    ledger["sessions"].append(session)
    save_ledger(path, ledger)
    print(
        f"Added session {paint(session['id'], BOLD)} — "
        f"{client}, {date}, {display_ml(ink_ml)} ml"
    )
    warning = patch_test_warning(ledger, client)
    if warning:
        print(warning)
    return 0


def ordered_sessions(sessions: list) -> list:
    indexed = list(enumerate(sessions))
    indexed.sort(
        key=lambda pair: (
            pair[1].get("date", ""),
            pair[1].get("created_at", ""),
            pair[0],
        ),
        reverse=True,
    )
    return [record for _, record in indexed]


def cmd_session_list(args, ledger: dict, path: str) -> int:
    sessions = ordered_sessions(ledger["sessions"])
    if not sessions:
        print(EMPTY_SESSIONS)
        return 0
    if getattr(args, "json", False):
        print(json.dumps({"sessions": sessions}, indent=2))
        return 0
    widths = [
        10,
        max(6, min(max(len(record.get("client", "")) for record in sessions), 26)),
        10,
        9,
    ]
    header = "  ".join(
        cell(title, width)
        for title, width in zip(("ID", "CLIENT", "DATE", "INK"), widths)
    )
    print(paint(header.rstrip(), BOLD))
    print(rule(sum(widths) + 6))
    for record in sessions:
        print(
            "  ".join(
                [
                    cell(record.get("id", ""), widths[0]),
                    cell(record.get("client", ""), widths[1]),
                    cell(record.get("date", ""), widths[2]),
                    cell(
                        display_ml(record.get("ink_ml", "0")) + " ml",
                        widths[3],
                        "right",
                    ),
                ]
            ).rstrip()
        )
    print(rule(sum(widths) + 6))
    count = len(sessions)
    print(f"{count} session{'s' if count != 1 else ''} · newest first")
    return 0


def latest_patch_test(ledger: dict, client: str):
    records = [r for r in ledger["patch_tests"] if r.get("client") == client]
    if not records:
        return None
    records.sort(key=lambda r: (r.get("date", ""), r.get("created_at", "")), reverse=True)
    return records[0]


def patch_test_warning(ledger: dict, client: str):
    latest = latest_patch_test(ledger, client)
    if latest is None or latest.get("outcome") != "fail":
        return None
    date = latest.get("date", "unknown date")
    return (
        paint("WARNING", ACCENT_ANSI)
        + f": most recent patch test for {client} ({date}) FAILED"
    )


# --- needle commands --------------------------------------------------------
def resolve_session(args, ledger: dict) -> dict:
    session_id = getattr(args, "session_id", None)
    if session_id is not None and str(session_id).strip():
        wanted = str(session_id).strip()
        for record in ledger["sessions"]:
            if record.get("id") == wanted:
                return record
        raise ValidationError(
            f"No session with id {wanted} — run: inkfathom session list"
        )
    client = getattr(args, "client", None)
    date = getattr(args, "date", None)
    if client is None and date is None:
        raise ValidationError(
            "--gauge needs a session: pass --session-id, or both --client and --date."
        )
    client = require_client(client)
    date = require_date(date)
    matches = [
        record
        for record in ledger["sessions"]
        if record.get("client") == client and record.get("date") == date
    ]
    if not matches:
        raise ValidationError(
            f"No session found for {client} on {date} — add one with: "
            f"inkfathom session add --client {client} --date {date} --ink-ml N"
        )
    if len(matches) > 1:
        candidates = ", ".join(record.get("id", "?") for record in matches)
        raise ValidationError(
            f"Session match is ambiguous for {client} on {date} — "
            f"candidate ids: {candidates}. Use --session-id."
        )
    return matches[0]


NEEDLE_ADD_USAGE = (
    "--gauge is required and needs a session: "
    "inkfathom needle add --session-id ID --gauge 0.30mm "
    "(or --client NAME --date YYYY-MM-DD instead of --session-id)"
)


def cmd_needle_add(args, ledger: dict, path: str) -> int:
    if getattr(args, "gauge", None) is None:
        raise ValidationError(NEEDLE_ADD_USAGE)
    gauge = require_gauge(getattr(args, "gauge", None))
    quantity = require_quantity(getattr(args, "quantity", None))
    session = resolve_session(args, ledger)
    use = {
        "id": new_id("N-", {record.get("id") for record in ledger["needle_uses"]}),
        "session_id": session["id"],
        "client": session.get("client", ""),
        "date": session.get("date", ""),
        "gauge": gauge,
        "quantity": quantity,
        "created_at": now_stamp(),
    }
    ledger["needle_uses"].append(use)
    save_ledger(path, ledger)
    print(
        f"Added needle use {paint(use['id'], BOLD)} — {use['client']}, "
        f"{use['session_id']}, {gauge} ×{quantity}"
    )
    return 0


def needle_tallies(ledger: dict, client) -> list:
    uses = ledger["needle_uses"]
    if client is not None:
        uses = [use for use in uses if use.get("client") == client]
    grouped: dict = {}
    for use in uses:
        gauges = grouped.setdefault(use.get("client", "(unknown)"), {})
        gauge = use.get("gauge", "?")
        gauges[gauge] = gauges.get(gauge, 0) + int(use.get("quantity", 0) or 0)
    tallies = []
    for name in sorted(grouped):
        gauges = grouped[name]
        tallies.append(
            {
                "client": name,
                "gauges": [
                    {"gauge": gauge, "count": count}
                    for gauge, count in sorted(gauges.items())
                ],
                "total": sum(gauges.values()),
            }
        )
    return tallies


def cmd_needle_list(args, ledger: dict, path: str) -> int:
    raw_client = getattr(args, "client", None)
    client = require_client(raw_client) if raw_client is not None else None
    tallies = needle_tallies(ledger, client)
    if not tallies:
        print(EMPTY_NEEDLES_CLIENT if client else EMPTY_NEEDLES_ALL)
        return 0
    if getattr(args, "json", False):
        print(json.dumps({"tallies": tallies}, indent=2))
        return 0
    for position, tally in enumerate(tallies):
        if position:
            print()
        print(paint(tally["client"], BOLD))
        print(rule(16))
        for entry in tally["gauges"]:
            print(f"{entry['gauge']}  {entry['count']}")
        print(f"{'total':<6}  {tally['total']}")
    return 0


# --- patch test commands ----------------------------------------------------
PATCHTEST_ADD_USAGE = (
    "--client, --date and --outcome are required: "
    "inkfathom patchtest add --client NAME --date YYYY-MM-DD --outcome pass|fail"
)


def cmd_patchtest_add(args, ledger: dict, path: str) -> int:
    if (
        getattr(args, "client", None) is None
        and getattr(args, "date", None) is None
        and getattr(args, "outcome", None) is None
    ):
        raise ValidationError(PATCHTEST_ADD_USAGE)
    client = require_client(getattr(args, "client", None))
    date = require_date(getattr(args, "date", None))
    outcome = require_outcome(getattr(args, "outcome", None))
    record = {
        "id": new_id("P-", {entry.get("id") for entry in ledger["patch_tests"]}),
        "client": client,
        "date": date,
        "outcome": outcome,
        "created_at": now_stamp(),
    }
    ledger["patch_tests"].append(record)
    save_ledger(path, ledger)
    print(
        f"Added patch test {paint(record['id'], BOLD)} — {client}, {date}, {outcome}"
    )
    return 0


def cmd_patchtest_list(args, ledger: dict, path: str) -> int:
    client = require_client(getattr(args, "client", None))
    records = [r for r in ledger["patch_tests"] if r.get("client") == client]
    if not records:
        print(EMPTY_PATCH_TESTS)
        return 0
    records.sort(key=lambda r: (r.get("date", ""), r.get("created_at", "")), reverse=True)
    if getattr(args, "json", False):
        payload = []
        for position, record in enumerate(records):
            entry = dict(record)
            entry["latest"] = position == 0
            payload.append(entry)
        print(json.dumps({"client": client, "patch_tests": payload}, indent=2))
        return 0
    print(paint(client, BOLD) + paint(" · patch tests, newest first", DIM))
    header = f"{'MARK':<6}  {'DATE':<10}  OUTCOME"
    print(paint(header, BOLD))
    print(rule(len(header)))
    for position, record in enumerate(records):
        marker = "latest" if position == 0 else ""
        print(
            f"{marker:<6}  {cell(record.get('date', ''), 10)}  "
            f"{record.get('outcome', '?')}"
        )
    print(rule(len(header)))
    return 0


# --- authentication commands ------------------------------------------------
def cmd_auth(args, path: str) -> int:
    ledger = load_ledger(path)
    if getattr(args, "auth_command", None) == "check":
        if not ledger.get("kdf"):
            raise AuthError(
                "This ledger has no passphrase yet — run: inkfathom auth setup"
            )
        authenticate(args, ledger, path, allow_setup=False)
        print("Passphrase accepted.")
        return 0
    created = authenticate(args, ledger, path, allow_setup=True)
    if created:
        print(f"Passphrase set for {path}")
        print(
            "Keep it safe — it is stored as a salted hash and cannot be recovered."
        )
    else:
        print("Passphrase already set for this ledger — nothing to change.")
    return 0


# --- command line -----------------------------------------------------------
def common_parser() -> argparse.ArgumentParser:
    """Flags every subcommand accepts, in the SUPPRESS style so a value given at
    any level survives argparse's subparser namespace merge."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--ledger",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="ledger file (default: ~/.inkfathom/ledger.json, or $INKFATHOM_LEDGER)",
    )
    common.add_argument(
        "--passphrase",
        metavar="PASSPHRASE",
        default=argparse.SUPPRESS,
        help="passphrase for scripted runs instead of the hidden prompt",
    )
    return common


ROOT_EPILOG = """\
command groups:
  auth       set or check the local passphrase that gates every command
  session    log a tattoo session and its ink volume in millilitres
  needle     record needle use and read the per-client tally by gauge
  patchtest  record a client patch test and read that client's history

one-line examples:
  inkfathom auth setup
  inkfathom session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 2.5
  inkfathom session list
  inkfathom needle add --client "Ada Reyes" --date 2024-05-02 --gauge 0.30mm --quantity 3
  inkfathom needle list --client "Ada Reyes"
  inkfathom patchtest add --client "Ada Reyes" --date 2024-04-20 --outcome fail
  inkfathom patchtest list --client "Ada Reyes"

The ledger is pretty-printed JSON at ~/.inkfathom/ledger.json; override it with
--ledger PATH or INKFATHOM_LEDGER. The first command on a fresh ledger asks for a
passphrase (stored only as a salted PBKDF2-HMAC-SHA256 hash); later commands
prompt for it, or take --passphrase for scripted runs. Fully offline.
"""

TAGLINE = "tattoo ink, needle gauge and patch-test ledger."
DESCRIPTION = f"InkFathom \u2014 {TAGLINE}"


def add_list_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print JSON for scripting")


def add_auth_commands(subparsers, common) -> None:
    auth = subparsers.add_parser(
        "auth",
        parents=[common],
        help="set or check the local passphrase",
        description="Set the ledger passphrase on first run, or check it later.",
        epilog="examples:\n  inkfathom auth setup\n  inkfathom auth check --passphrase ...",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    auth_sub = auth.add_subparsers(dest="auth_command", metavar="{setup,check}")
    auth_sub.add_parser(
        "setup",
        parents=[common],
        help="set the passphrase on a fresh ledger (safe to re-run)",
        description="Store a salted PBKDF2-HMAC-SHA256 hash of the passphrase.",
        epilog="example:\n  inkfathom auth setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    auth_sub.add_parser(
        "check",
        parents=[common],
        help="verify the passphrase without changing the ledger",
        description="Verify the passphrase; exit 1 when it is not recognised.",
        epilog="example:\n  inkfathom auth check --passphrase ...",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def add_session_commands(subparsers, common) -> None:
    session = subparsers.add_parser(
        "session",
        parents=[common],
        help="log tattoo sessions and their ink volume",
        description="Record one ledger entry per tattoo session and read them back.",
        epilog=(
            "examples:\n"
            '  inkfathom session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 2.5\n'
            "  inkfathom session list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    session_sub = session.add_subparsers(dest="session_command", metavar="{add,list}")
    session_add = session_sub.add_parser(
        "add",
        parents=[common],
        help="record a session with its ink volume",
        description="Record a session; prints the new S-xxxxxx id.",
        epilog=(
            "example:\n"
            '  inkfathom session add --client "Ada Reyes" --date 2024-05-02 --ink-ml 2.5'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    session_add.add_argument("--client", metavar="NAME", help="client name (1-80 characters)")
    session_add.add_argument("--date", metavar="YYYY-MM-DD", help="session date")
    session_add.add_argument("--ink-ml", metavar="ML", help="ink volume in millilitres")
    session_list = session_sub.add_parser(
        "list",
        parents=[common],
        help="list sessions newest first (id, client, date, ink ml)",
        description="List every session, newest date first.",
        epilog="example:\n  inkfathom session list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_list_options(session_list)


def add_needle_commands(subparsers, common) -> None:
    needle = subparsers.add_parser(
        "needle",
        parents=[common],
        help="record needle use and read the per-client gauge tally",
        description="Record needle use against a session; tally needles per client by gauge.",
        epilog=(
            "examples:\n"
            "  inkfathom needle add --session-id S-1a2b3c --gauge 0.30mm --quantity 3\n"
            '  inkfathom needle add --client "Ada Reyes" --date 2024-05-02 --gauge 0.25mm\n'
            "  inkfathom needle list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    needle_sub = needle.add_subparsers(dest="needle_command", metavar="{add,list}")
    needle_add = needle_sub.add_parser(
        "add",
        parents=[common],
        help="record needle use against a session",
        description="Target the session with --session-id, or a unique --client and --date.",
        epilog=(
            "examples:\n"
            "  inkfathom needle add --session-id S-1a2b3c --gauge 0.30mm --quantity 3\n"
            '  inkfathom needle add --client "Ada Reyes" --date 2024-05-02 --gauge 0.25mm'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    needle_add.add_argument("--session-id", metavar="ID", help="session id such as S-1a2b3c")
    needle_add.add_argument("--client", metavar="NAME", help="client name, used with --date")
    needle_add.add_argument("--date", metavar="YYYY-MM-DD", help="session date, used with --client")
    needle_add.add_argument("--gauge", metavar="GAUGE", help="needle gauge such as 0.30mm")
    needle_add.add_argument("--quantity", metavar="N", help="whole number of needles (default 1)")
    needle_list = needle_sub.add_parser(
        "list",
        parents=[common],
        help="tally needles per client by gauge",
        description="Print one line per gauge with its total, per client.",
        epilog='example:\n  inkfathom needle list --client "Ada Reyes"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    needle_list.add_argument("--client", metavar="NAME", help="limit the tally to one client")
    add_list_options(needle_list)


def add_patchtest_commands(subparsers, common) -> None:
    patchtest = subparsers.add_parser(
        "patchtest",
        parents=[common],
        help="record client patch tests and read their history",
        description="Store patch test results per client; the latest one is marked.",
        epilog=(
            "examples:\n"
            '  inkfathom patchtest add --client "Ada Reyes" --date 2024-04-20 --outcome fail\n'
            '  inkfathom patchtest list --client "Ada Reyes"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    patchtest_sub = patchtest.add_subparsers(
        dest="patchtest_command", metavar="{add,list}"
    )
    patchtest_add = patchtest_sub.add_parser(
        "add",
        parents=[common],
        help="record a patch test with outcome pass or fail",
        description="Record a client patch test; prints the new P-xxxxxx id.",
        epilog=(
            "example:\n"
            '  inkfathom patchtest add --client "Ada Reyes" --date 2024-04-20 --outcome pass'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    patchtest_add.add_argument("--client", metavar="NAME", help="client name")
    patchtest_add.add_argument("--date", metavar="YYYY-MM-DD", help="patch test date")
    patchtest_add.add_argument("--outcome", metavar="PASS|FAIL", help="pass or fail")
    patchtest_list = patchtest_sub.add_parser(
        "list",
        parents=[common],
        help="list one client's patch tests, latest marked",
        description="List a client's patch tests by date; the newest is marked latest.",
        epilog='example:\n  inkfathom patchtest list --client "Ada Reyes"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    patchtest_list.add_argument("--client", metavar="NAME", help="client name")
    add_list_options(patchtest_list)


def build_parser() -> argparse.ArgumentParser:
    common = common_parser()
    parser = InkFathomParser(
        prog="inkfathom",
        description=DESCRIPTION,
        epilog=ROOT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"inkfathom {VERSION}")
    subparsers = parser.add_subparsers(
        dest="command", metavar="{auth,session,needle,patchtest}"
    )
    add_auth_commands(subparsers, common)
    add_session_commands(subparsers, common)
    add_needle_commands(subparsers, common)
    add_patchtest_commands(subparsers, common)
    return parser


HANDLERS = {
    "session_add": cmd_session_add,
    "session_list": cmd_session_list,
    "needle_add": cmd_needle_add,
    "needle_list": cmd_needle_list,
    "patchtest_add": cmd_patchtest_add,
    "patchtest_list": cmd_patchtest_list,
}


def banner(parser: argparse.ArgumentParser, args) -> None:
    ledger_path = resolve_ledger_path(args)
    print(paint("INKFATHOM", BOLD) + f" {VERSION} · {TAGLINE}")
    print(paint(f"ledger: {ledger_path}", DIM))
    print()
    parser.print_help()


def dispatch(args, parser: argparse.ArgumentParser) -> int:
    command = getattr(args, "command", None)
    if command is None:
        banner(parser, args)
        return 0
    path = resolve_ledger_path(args)
    if command == "auth":
        return cmd_auth(args, path)
    subgroup = getattr(args, f"{command}_command", None)
    handler = HANDLERS.get(f"{command}_{subgroup}") if subgroup else None
    if handler is None:
        raise UsageError(
            f"'inkfathom {command}' needs a subcommand: "
            f"run 'inkfathom {command} --help'."
        )
    ledger = load_ledger(path)
    created = authenticate(args, ledger, path)
    if created:
        emit_notice("Passphrase set. Keep it safe — it cannot be recovered.")
    return handler(args, ledger, path)


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return dispatch(args, parser)
    except SystemExit as exc:
        return int(exc.code or 0)
    except InkFathomError as exc:
        emit_error(str(exc))
        return exc.exit_code
    except OSError as exc:
        emit_error(f"I/O error: {exc.strerror or exc}")
        return 1
    except KeyboardInterrupt:
        emit_error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
