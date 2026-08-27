#!/usr/bin/env python3
"""Build server/.venv/Scripts/Ratchet.exe — an interpreter Windows labels
"Ratchet" instead of "Python".

Task Manager's Processes tab shows the FileDescription from a program's version
resource (its Details tab shows the file name), so a Python service is listed as
"Python" no matter what the launcher is called.

Two things follow from how venv works on Windows, and both matter here:

* Since Python 3.7.2 the Scripts directory holds *redirector scripts* for
  python[w].exe rather than copies of the binaries. A redirector starts the
  base interpreter and exits, so the process that survives runs the base
  pythonw.exe — renaming or restamping the redirector changes nothing. The
  copy therefore has to be made from sys.base_prefix.
* A copied interpreter still finds this virtualenv, because PEP 405 looks for
  pyvenv.cfg "either adjacent to the Python executable or one directory above
  it", and .venv/Scripts/Ratchet.exe sits one directory below .venv/pyvenv.cfg.
  PEP 405 states the technique "works equally well ... with a copied or
  symlinked Python binary"; symlinks are what venv itself avoids on Windows.

Two caveats come with the copy, both from PEP 405:

* It needs the interpreter's DLLs to be findable. They live beside the base
  interpreter, which the Python installer puts on PATH; if that ever stops
  being true the copy will not start, so this script runs it once before
  accepting it and refuses to leave a broken launcher behind.
* A copied binary can drift out of step with the standard library when Python
  is upgraded. Re-running this script re-copies from the current interpreter,
  which is also needed after recreating the virtualenv.

Ratchet.vbs uses this executable when it is present and falls back to
pythonw.exe when it is not, so skipping this step costs only the name.

Usage:  python scripts/make_launcher_exe.py
"""

from __future__ import annotations

import ctypes
import shutil
import struct
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

VENV_SCRIPTS = Path(__file__).resolve().parents[1] / ".venv" / "Scripts"
TARGET = VENV_SCRIPTS / "Ratchet.exe"
# The real interpreter, not the venv's redirector — see the note above.
SOURCE = Path(sys.base_prefix) / "pythonw.exe"

RT_VERSION = 16
VERSION_ID = 1
LANG_EN_US = 0x0409
CODEPAGE_UNICODE = 0x04B0

FIELDS = {
    "CompanyName": "Ratchet",
    "FileDescription": "Ratchet",      # this is the string Task Manager shows
    "FileVersion": "1.0.0.0",
    "InternalName": "Ratchet",
    "OriginalFilename": "Ratchet.exe",
    "ProductName": "Ratchet",
    "ProductVersion": "1.0.0.0",
}


def _pad(data: bytes) -> bytes:
    """Every node in a version resource starts on a 4-byte boundary."""
    return data + b"\0" * (-len(data) % 4)


def _node(key: str, value: bytes, value_len: int, is_text: bool,
          children: bytes = b"") -> bytes:
    """One version-resource node: header, key, value, then any children.

    wLength covers the whole node, while wValueLength counts characters for
    text values but bytes for binary ones — the quirk that makes this format
    worth building deliberately rather than by hand.
    """
    head = struct.pack("<HHH", 0, value_len, 1 if is_text else 0)
    head += key.encode("utf-16-le") + b"\0\0"
    body = _pad(head) + value
    if children:
        body = _pad(body) + children
    return struct.pack("<H", len(body)) + body[2:]


def _string(key: str, value: str) -> bytes:
    # Text values count WCHARs, including the terminator.
    return _node(key, value.encode("utf-16-le") + b"\0\0", len(value) + 1, True)


def _fixed_file_info() -> bytes:
    return struct.pack(
        "<LLLLLLLLLLLLL",
        0xFEEF04BD,     # signature
        0x00010000,     # struct version
        0x00010000, 0,  # file version    1.0.0.0
        0x00010000, 0,  # product version 1.0.0.0
        0x3F, 0,        # flags mask, flags
        0x00040004,     # VOS_NT_WINDOWS32
        0x00000001,     # VFT_APP
        0, 0, 0,        # subtype, date
    )


def version_resource() -> bytes:
    strings = b"".join(_pad(_string(k, v)) for k, v in FIELDS.items())
    table = _node(f"{LANG_EN_US:04x}{CODEPAGE_UNICODE:04x}", b"", 0, True, strings)
    string_info = _node("StringFileInfo", b"", 0, True, _pad(table))
    translation = _node("Translation",
                        struct.pack("<HH", LANG_EN_US, CODEPAGE_UNICODE), 4, False)
    var_info = _node("VarFileInfo", b"", 0, True, _pad(translation))
    return _node("VS_VERSION_INFO", _fixed_file_info(), 52, False,
                 _pad(string_info) + _pad(var_info))


def stamp(path: Path, data: bytes) -> None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.WORD,
                                    wintypes.LPVOID, wintypes.DWORD]
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]

    handle = k32.BeginUpdateResourceW(str(path), False)
    if not handle:
        raise OSError(ctypes.get_last_error(), "BeginUpdateResource failed")
    ok = k32.UpdateResourceW(handle, ctypes.cast(RT_VERSION, wintypes.LPCWSTR),
                             ctypes.cast(VERSION_ID, wintypes.LPCWSTR),
                             LANG_EN_US, data, len(data))
    if not ok:
        k32.EndUpdateResourceW(handle, True)      # discard
        raise OSError(ctypes.get_last_error(), "UpdateResource failed")
    if not k32.EndUpdateResourceW(handle, False):
        raise OSError(ctypes.get_last_error(), "EndUpdateResource failed")


def works(path: Path) -> bool:
    """Does the copy start, and does it still resolve to this virtualenv?

    Checked rather than assumed: it is launched with no console, so a copy
    that cannot find the interpreter DLLs would fail invisibly at login.
    """
    probe = "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 3)"
    try:
        return subprocess.run([str(path), "-c", probe], timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    if sys.platform != "win32":
        print("Windows only; nothing to do.")
        return 0
    if not SOURCE.is_file():
        print(f"ERROR: base interpreter not found at {SOURCE}")
        return 1
    if not VENV_SCRIPTS.is_dir():
        print(f"ERROR: {VENV_SCRIPTS} not found — create the virtualenv first.")
        return 1

    shutil.copy2(SOURCE, TARGET)
    stamp(TARGET, version_resource())

    if not works(TARGET):
        TARGET.unlink(missing_ok=True)
        print("ERROR: the copy would not start or did not pick up the "
              "virtualenv, so it has been removed. Ratchet.vbs will keep "
              "using pythonw.exe; only the Task Manager name is affected.")
        return 1

    print(f"wrote {TARGET}")
    print(f'Task Manager will show it as "{FIELDS["FileDescription"]}".')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
