"""What Ratchet says when a FanFicFare run fails.

The tail of the output is whatever it last happened to print, and a killed
process prints nothing on the way out — so an add killed part-way through
was once recorded as having failed because of a PIL warning. The message
now leads with what ended the process, and a warning is called one.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet.sites import explain_failure  # noqa: E402

# As recorded in the audit log on 2026-09-09, verbatim: the whole of what a
# run killed from outside had printed. Not one word of it is the cause.
PIL_WARNING = (
    r"C:\Users\x\server\.venv\Lib\site-packages\PIL\Image.py:1136: "
    "UserWarning: Palette images with Transparency expressed in bytes should "
    "be converted to RGBA images\n  warnings.warn(\n")


def ran(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_a_killed_run_is_said_to_have_been_killed_not_to_have_warned():
    got = explain_failure(ran(0xFFFFFFFF, stderr=PIL_WARNING))
    assert got.startswith("fanficfare was stopped from outside")
    assert "reported no error, only a warning" in got
    assert "Palette images" in got            # still there, as context


def test_task_managers_exit_code_is_not_called_a_kill():
    """1 is also what an unhandled Python exception exits with, so the code
    alone cannot say; the output has to."""
    got = explain_failure(ran(1, stderr=PIL_WARNING))
    assert got.startswith("fanficfare exited with code 1")
    assert "reported no error, only a warning" in got


def test_a_real_error_leads_and_a_warning_beside_it_does_not():
    stderr = (PIL_WARNING +
              "Traceback (most recent call last):\n"
              '  File "cli.py", line 9, in <module>\n'
              "FileNotFoundError: [Errno 2] No such file or directory: 'x.epub'\n")
    got = explain_failure(ran(1, stderr=stderr))
    assert got.startswith("fanficfare exited with code 1: ")
    assert "FileNotFoundError" in got and "Traceback" in got
    assert "Palette images" not in got        # the warning is not the story
    assert "no error" not in got


def test_an_error_on_stdout_counts_too():
    got = explain_failure(ran(1, stdout="ERROR: story not found at that URL\n"))
    assert "ERROR: story not found" in got


def test_a_run_that_said_nothing_says_so():
    assert explain_failure(ran(1)) == "fanficfare exited with code 1 and printed nothing"


def test_output_that_is_neither_error_nor_warning_is_shown_as_its_last_line():
    got = explain_failure(ran(1, stdout="Downloading chapter 3 of 40\n"
                                        "Downloading chapter 4 of 40\n"))
    assert got == ("fanficfare exited with code 1; its last output: "
                   "Downloading chapter 4 of 40")


def test_several_warnings_are_counted_and_the_last_shown():
    got = explain_failure(ran(1, stderr="a: DeprecationWarning: one\n"
                                        "b: UserWarning: two\n"))
    assert "only 2 warnings, the last: b: UserWarning: two" in got


def test_a_signal_on_posix_is_named():
    assert explain_failure(ran(-9)).startswith("fanficfare was killed by signal 9")


def test_windows_control_c_and_a_crash_are_named():
    assert "interrupted" in explain_failure(ran(0xC000013A))
    assert "crashed" in explain_failure(ran(0xC0000005))


def test_the_name_of_the_run_is_the_callers_to_choose():
    assert explain_failure(ran(1), "fanficfare -u").startswith("fanficfare -u exited")


def test_a_long_error_is_cut_from_the_front_not_the_end():
    """The last lines of a traceback are the ones that say what went wrong."""
    stderr = "Traceback\n" + "\n".join(f"  File line {i}" for i in range(400)) + \
             "\nValueError: the actual reason\n"
    got = explain_failure(ran(1, stderr=stderr))
    assert got.endswith("ValueError: the actual reason")
    assert len(got) < 1000
