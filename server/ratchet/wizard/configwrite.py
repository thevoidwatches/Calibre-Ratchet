"""Change values in config.toml and .env without disturbing anything else.

A config file that has been lived in is full of things no writer would
reproduce: comments saying why a value is what it is, a temporary setting
with the date it was made, keys in an order that made sense to whoever put
them there. Python can read TOML but not write it, and the libraries that do
write it start from the parsed values, so everything that was not a value is
lost. The setup wizard only ever wants to change a handful of settings, so
it edits the text instead: the lines it was asked to change are changed, and
every other byte of the file is left as it was.

Both functions are pure — text in, text out — so the wizard decides where
the files live and these can be tested without any.
"""

from __future__ import annotations

import json
import re
import tomllib

_SECTION = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")


class ConfigEditError(ValueError):
    """The file cannot be edited safely; nothing should be written."""


def _newline_of(text: str) -> str:
    """The line ending a file already uses, so that it keeps it. A file made
    on Windows ends its lines CR LF, and one rewritten with bare LF has
    changed on every line as far as any diff is concerned — which is not
    "every other byte left as it was"."""
    return "\r\n" if "\r\n" in text else "\n"


def toml_value(value: object) -> str:
    """A Python value as TOML source. Strings, whole numbers, booleans and
    flat lists of them are all the wizard sets."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # A TOML basic string and a JSON string escape the same way.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise ConfigEditError(f"cannot write a {type(value).__name__} to config.toml")


def _value_end(rest: str) -> int | None:
    """How far into `rest` (what follows "key =") the value reaches, or None
    when it does not finish on this line.

    Only as much of TOML as it takes to find the end: a quoted string ends at
    its closing quote, an array at its closing bracket, and anything else at
    a comment or the end of the line. A "#" inside a string is part of the
    string, which is the whole reason this is not a split on "#".
    """
    i = 0
    n = len(rest)
    while i < n and rest[i] in " \t":
        i += 1
    if i == n:
        return i
    if rest.startswith(('"""', "'''"), i):
        return None                                  # multi-line string
    if rest[i] in "\"'":
        quote = rest[i]
        j = i + 1
        while j < n:
            if rest[j] == "\\" and quote == '"':
                j += 2
                continue
            if rest[j] == quote:
                return j + 1
            j += 1
        return None
    if rest[i] == "[":
        depth, j, quote = 0, i, ""
        while j < n:
            c = rest[j]
            if quote:
                if c == "\\" and quote == '"':
                    j += 1
                elif c == quote:
                    quote = ""
            elif c in "\"'":
                quote = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return j + 1
            elif c == "#":
                return None                          # comment inside: multi-line
            j += 1
        return None                                  # closes on a later line
    j = i
    while j < n and rest[j] != "#":
        j += 1
    return len(rest[:j].rstrip())


def _set_line(line: str, key: str, value: object) -> str | None:
    """`line` with this key's value replaced, or None if it sets another key.

    A trailing comment is kept, and kept in the column it was in where the
    new value leaves room, so a block of aligned comments stays aligned.
    """
    m = re.match(rf"^(\s*{re.escape(key)}\s*=)(.*)$", line)
    if not m:
        return None
    head, rest = m.group(1), m.group(2)
    end = _value_end(rest)
    if end is None:
        raise ConfigEditError(
            f"'{key}' is set across several lines in config.toml, which the "
            "wizard will not rewrite — change it by hand")
    tail = rest[end:]
    new = f"{head} {toml_value(value)}"
    if tail.strip():
        comment_col = len(head) + end + (len(tail) - len(tail.lstrip()))
        new = new.ljust(comment_col - 1) + " " + tail.lstrip()
    return new


def set_values(text: str, values: dict[tuple[str, str], object]) -> str:
    """`text` with each (section, key) set to its value.

    A key that is there is changed where it stands. One that is not is added
    at the end of its section, and a section that is not there is added at
    the end of the file. Nothing else moves.

    The result is parsed before it is returned, and each value read back: an
    edit that did not take, or that broke the file, raises rather than
    reaching the disk.
    """
    newline = _newline_of(text)
    lines = text.splitlines()
    todo = dict(values)
    section = ""
    section_last: dict[str, int] = {}      # section -> its last non-blank line

    for i, line in enumerate(lines):
        header = _SECTION.match(line)
        if header:
            section = header.group(1).strip()
            section_last[section] = i
            continue
        if line.strip():
            section_last[section] = i
        if line.lstrip().startswith("#"):
            continue
        for (sec, key), value in list(todo.items()):
            if sec != section:
                continue
            new = _set_line(line, key, value)
            if new is not None:
                lines[i] = new
                del todo[(sec, key)]
                break

    # Added bottom-up, so an insertion does not shift the line numbers the
    # remaining ones were recorded against.
    additions: dict[str, list[str]] = {}
    for (sec, key), value in todo.items():
        additions.setdefault(sec, []).append(f"{key} = {toml_value(value)}")
    for sec in sorted((s for s in additions if s in section_last),
                      key=lambda s: section_last[s], reverse=True):
        at = section_last[sec] + 1
        lines[at:at] = additions.pop(sec)
    for sec, new_lines in additions.items():
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{sec}]")
        lines.extend(new_lines)

    out = "\n".join(lines) + "\n"
    try:
        parsed = tomllib.loads(out)
    except tomllib.TOMLDecodeError as e:
        raise ConfigEditError(f"the edit would leave config.toml unreadable: {e}")
    for (sec, key), value in values.items():
        got = parsed.get(sec, {}).get(key)
        if got != (list(value) if isinstance(value, tuple) else value):
            raise ConfigEditError(
                f"setting [{sec}] {key} did not take (read back {got!r})")
    return out.replace("\n", newline)


def set_env(text: str, values: dict[str, str]) -> str:
    """`text` (a .env file) with each variable set, other lines untouched.

    Values are written bare. The service's reader strips one pair of matching
    quotes, so a value that begins and ends with the same quote mark gets a
    pair of the other kind around it, to come back as it went in.
    """
    def line_for(name: str, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ConfigEditError(f"{name} cannot contain a line break")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            wrap = "'" if value[0] == '"' else '"'
            value = f"{wrap}{value}{wrap}"
        elif value != value.strip():
            value = f'"{value}"'                     # keep the edge spaces
        return f"{name}={value}"

    lines = text.splitlines()
    todo = dict(values)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name in todo:
            lines[i] = line_for(name, todo.pop(name))
    lines.extend(line_for(name, value) for name, value in todo.items())
    newline = _newline_of(text)
    return newline.join(lines) + newline
