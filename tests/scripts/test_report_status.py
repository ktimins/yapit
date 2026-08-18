"""The daily health report notifies only when it found issues, so the verdict it
reads out of its own text is what stands between a real problem and silence.

`scripts/report.sh --classify` prints that verdict for a report on stdin. The
cases here are the shapes real reports have arrived in: the status line first as
the prompt asks, the status line behind a sentence of preamble, as a markdown
heading, and carrying both a green and a warning marker at once.
"""

import subprocess
from pathlib import Path

import pytest

REPORT_SH = Path(__file__).resolve().parents[2] / "scripts" / "report.sh"


def classify(text: str) -> str:
    done = subprocess.run(
        ["bash", str(REPORT_SH), "--classify"], input=text, capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.mark.parametrize(
    "verdict,report",
    [
        ("nominal", "✅ **All nominal**\n\n## Summary\n\nEverything is fine.\n"),
        ("issues", "⚠️ **Issues detected**\n\n## Summary\n\nThe billing consumer died.\n"),
        ("anomalies", "🔍 **Anomalies noted**\n\n## Summary\n\nTraffic doubled.\n"),
        ("issues", "## ⚠️ Issues detected\n\nThe queue backed up.\n"),
        # Preamble before the status line: against the prompt, but it happens.
        ("nominal", "Session: abc\n---\n\nAll clear. Full picture assembled.\n\n✅ **All nominal**\n"),
        # Both markers on one line — the warning is the one that has to get through.
        ("issues", "✅ **All nominal** on the pipeline — ⚠️ **but the metrics pipeline is dark**\n"),
        # A green line first, a warning further down in the body: the report said
        # it was fine, and the detail below is what the reader opens it for.
        ("nominal", "✅ **All nominal**\n\n## Issues\n\n⚠️ one stale billing webhook, self-healed\n"),
        ("unknown", "Analysis complete.\n\nNothing to report today.\n"),
        # Past the head this stops looking: a marker 30 lines down is a section
        # heading in the body, not the status line.
        ("unknown", "Analysis complete.\n" + "\n" * 30 + "⚠️ **Issues detected**\n"),
    ],
)
def test_classify(verdict: str, report: str) -> None:
    assert classify(report) == verdict


def test_classify_reads_bare_warning_sign() -> None:
    """The warning sign arrives both with and without its emoji variation
    selector, and both mean the same thing.
    """
    assert classify("⚠️ **Issues detected**\n") == "issues"
    assert classify("⚠ **Issues detected**\n") == "issues"
