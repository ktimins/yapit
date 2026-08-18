"""The dependency scout notifies only when its report found something needing a
person, so the verdict it reads out of its own status line is what stands between
a security fix nobody heard about and silence.

`scripts/dep-scout.sh --classify` prints that verdict for a report on stdin. The
cases here are the shapes reports arrive in: the status line first as the prompt
asks, behind a session header, behind a sentence of preamble, and missing entirely
— which is every report written before the prompt promised one.
"""

import subprocess
from pathlib import Path

import pytest

DEP_SCOUT_SH = Path(__file__).resolve().parents[2] / "scripts" / "dep-scout.sh"
SAVED_REPORTS = sorted((Path.home() / "logs" / "yapit-reports").glob("dep-scout-*.md"))
VERDICTS = {"actionable", "routine", "unknown"}


def classify(text: str) -> str:
    done = subprocess.run(
        ["bash", str(DEP_SCOUT_SH), "--classify"], input=text, capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.mark.parametrize(
    "verdict,report",
    [
        ("actionable", "⚠️ **Action required** — playwright ships Chromium 147, an exploited V8 bug behind\n"),
        ("routine", "✅ **Nothing to act on** — 31 advisories, all build or dev tooling\n"),
        # As the file is saved: the session header sits in front of the report.
        ("actionable", "Dep Scout — Session: abc\n---\n\n⚠️ **Action required** — PyMuPDF parses uploads\n"),
        # Preamble before the status line: against the prompt, but it happens.
        ("routine", "Dep Scout — Session: abc\n---\n\nEverything's verified.\n\n✅ **Nothing to act on**\n"),
        # Both markers on one line — the one asking for work has to get through.
        ("actionable", "✅ **Nothing to act on** in the frontend — ⚠️ **but defuddle needs a bump**\n"),
        # A tier heading further down is not the status line: the report never
        # said how it went, and unreadable is not the same as nothing to do.
        ("unknown", "## Tier 1\n" + "\n" * 30 + "⚠️ **Action required** — undici\n"),
        ("unknown", "# Dependency Analysis\n\n## Executive summary\n\n29 advisories, nothing reachable.\n"),
    ],
)
def test_classify(verdict: str, report: str) -> None:
    assert classify(report) == verdict


def test_classify_reads_bare_warning_sign() -> None:
    """The warning sign arrives both with and without its emoji variation
    selector, and both mean the same thing.
    """
    assert classify("⚠️ **Action required** — undici\n") == "actionable"
    assert classify("⚠ **Action required** — undici\n") == "actionable"


def test_classify_reads_a_report_with_no_newline_at_the_end() -> None:
    """The agent's result arrives as a string, not as a file, and its last line
    often has no newline after it. When the status line is that line, reading it
    is the difference between a notification and silence.
    """
    assert classify("✅ **Nothing to act on** — 31 advisories, all tooling") == "routine"
    assert classify("⚠️ **Action required** — undici") == "actionable"


def test_classify_survives_a_report_too_long_for_a_pipe() -> None:
    """A verdict is read out of the opening lines, but the whole report still has
    to go in: a report bigger than a pipe buffer would otherwise kill the run that
    had just saved it and not yet notified.
    """
    report = "⚠️ **Action required** — undici\n\n## Tier 4\n" + "- a patch bump\n" * 40000
    assert len(report) > 400_000
    assert classify(report) == "actionable"


@pytest.mark.skipif(not SAVED_REPORTS, reason="no saved scout reports on this machine")
@pytest.mark.parametrize("path", SAVED_REPORTS, ids=[p.stem for p in SAVED_REPORTS])
def test_saved_reports_are_never_read_as_silence(path: Path) -> None:
    """Every report the scout has ever written, against the one rule that matters:
    silence needs the report's own check mark. Reports predating the status line
    read as `unknown` and notify — two of them lead with an actively-exploited
    Chromium bug, and prose full of "critical" must never talk this into `routine`.
    """
    body = path.read_text(errors="replace")
    verdict = classify(body)
    assert verdict in VERDICTS
    if "✅" not in body:
        assert verdict != "routine"
    if "⚠" not in body and "✅" not in body:
        assert verdict == "unknown"
