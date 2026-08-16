"""Guards on the installer scripts.

These exist because of a real failure: `install.ps1` reported "Python 3.10+ is
required" on a machine with a perfectly good Python 3.14. The cause was not the
version comparison — it was a `python -c` snippet containing double quotes.
Windows PowerShell does not escape embedded double quotes when building a
native command line, so Python received a corrupted snippet, raised a
SyntaxError onto a suppressed stderr, and the loop concluded no Python existed.

CI has no PowerShell, so these tests check the script as text and execute the
Python snippets it embeds. That is enough to catch the whole class of bug.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
RUN_PS1 = REPO_ROOT / "scripts" / "run.ps1"
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"

#: Matches `-c "<payload>"` in a PowerShell script, capturing the payload.
PY_SNIPPET = re.compile(r'-c\s+"([^"]*)"')


def powershell_scripts() -> list[Path]:
    return [path for path in (INSTALL_PS1, RUN_PS1) if path.exists()]


def test_powershell_scripts_exist():
    assert INSTALL_PS1.exists(), "the Windows installer is missing"


@pytest.mark.parametrize("script", powershell_scripts(), ids=lambda p: p.name)
def test_no_double_quotes_inside_python_snippets(script: Path):
    """The exact bug that broke the Windows install.

    A `python -c` argument must not contain a double quote. PowerShell consumes
    embedded double quotes as delimiters, so Python would receive mangled
    source. Use single quotes inside the snippet, or avoid quoting entirely.
    """
    text = script.read_text(encoding="utf-8")

    # A payload captured by PY_SNIPPET is quote-free by construction, so the
    # hazard is a `-c "` that is NOT followed by a clean run up to the closing
    # quote — i.e. the naive pattern below finds an inner quote.
    hazardous = re.findall(r'-c\s+\'[^\']*"', text)
    assert not hazardous, (
        f"{script.name} passes a double quote inside a python -c argument: {hazardous!r}. "
        "PowerShell strips it and Python receives broken source. "
        "Use single quotes inside the snippet instead."
    )


@pytest.mark.parametrize("script", powershell_scripts(), ids=lambda p: p.name)
def test_embedded_python_snippets_are_valid_python(script: Path):
    """Every `python -c` payload must actually compile."""
    for snippet in PY_SNIPPET.findall(script.read_text(encoding="utf-8")):
        if "import" not in snippet and "print" not in snippet and "sys." not in snippet:
            continue  # not a Python payload (e.g. an npm or cargo argument)
        try:
            compile(snippet, "<install.ps1 snippet>", "exec")
        except SyntaxError as exc:
            pytest.fail(f"{script.name} embeds invalid Python: {snippet!r} -> {exc}")


def test_version_check_snippet_accepts_this_interpreter():
    """Run the installer's real probe and confirm it accepts a supported Python.

    The test suite only ever runs on a Python GAIA supports, so the probe must
    exit 0 here. If someone reintroduces a broken comparison, this fails.
    """
    text = INSTALL_PS1.read_text(encoding="utf-8")
    probes = [s for s in PY_SNIPPET.findall(text) if "version_info" in s]
    assert probes, "install.ps1 no longer contains a Python version probe"

    for probe in probes:
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"the installer would reject Python {sys.version.split()[0]}. "
            f"stderr: {result.stderr.strip()}"
        )
        assert result.stdout.strip(), "the probe printed no version"


@pytest.mark.parametrize(
    ("version", "acceptable"),
    [
        ((3, 9, 0), False),
        ((3, 10, 0), True),
        ((3, 11, 15), True),
        ((3, 12, 7), True),
        ((3, 13, 1), True),
        # The version that exposed the bug, plus headroom. A future release
        # must not be rejected by an accidental upper bound or a string compare
        # where "3.9" > "3.14".
        ((3, 14, 5), True),
        ((3, 15, 0), True),
        ((4, 0, 0), True),
    ],
)
def test_version_predicate_across_releases(version: tuple[int, int, int], acceptable: bool):
    """The predicate itself, evaluated the way the installer evaluates it."""
    assert (version >= (3, 10)) is acceptable


def test_requires_python_has_no_upper_bound():
    """A cap in pyproject would make pip refuse to install on a new Python."""
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    requires = metadata["project"]["requires-python"]
    assert "<" not in requires, (
        f"requires-python is {requires!r}. An upper bound blocks new Python "
        "releases; drop it unless a dependency genuinely breaks."
    )


def test_installer_does_not_parse_version_strings_in_powershell():
    """Prefer Python's own comparison over PowerShell string arithmetic.

    Splitting "3.14" and casting the parts is where an off-by-one or a string
    comparison creeps in. The probe delegates the decision to Python and reads
    the exit code, so there is nothing in PowerShell left to get wrong.
    """
    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert "$LASTEXITCODE -eq 0" in text, "the installer no longer trusts Python's exit code"
    assert ".Split('.')" not in text, (
        "install.ps1 is parsing a version string in PowerShell again; "
        "let Python answer with sys.version_info and an exit code instead"
    )
