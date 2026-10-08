"""Edit the signing director's credentials in config/settings.yaml, in place.

The one place in this application that writes to settings.yaml, and deliberately
the narrowest one possible: it rewrites the five value spans under
``portal.director`` and touches no other byte of the file.

Why not ``yaml.safe_dump``
--------------------------
Because a round-trip through PyYAML would be a data-loss bug wearing the clothes
of a one-liner. ``settings.yaml`` is ~310 lines of which a large fraction are
comments, and those comments are the documentation: why the takeover budget is
900 seconds and not 300, why the director's name is three keys rather than one,
why the placeholder standard is knowingly false on the form. ``safe_dump``
deletes every one of them, sorts the keys, and — defaulting to
``allow_unicode=False`` — rewrites ``"TESTƏROV"`` as ``"TEST\\u018fROV"``.
The user would have pressed Save on a name field and lost the file's entire
rationale.

So this reads with the parser and writes with a scalpel. The cost is that it
only understands one shape of one block; that is the intended trade, and it
refuses rather than guesses when the file does not have that shape.

Safety
------
``config/settings.yaml`` is git-ignored (.gitignore:2-4), so a bad write has no
``git checkout`` behind it. Every write therefore leaves a ``.bak``, lands via
``os.replace``, and is read back through ``yaml.safe_load`` before it is allowed
to stand — a settings file the pipeline can no longer parse is a worse outcome
than a refused edit, so a failed read-back restores the backup and raises.

I/O contract
------------
read_director(path) -> dict[str, str]     # every key present, missing ones ""
write_director(path, values) -> None      # raises SettingsWriteError
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

#: The five boxes the portal actually has. Order is the order they are written
#: in when a key has to be appended, and the order the form shows them in.
#: ``fin`` and ``seriya_nomresi`` are the two the uploader refuses --live
#: without (uploader.py:665-674); the name parts are filled by the portal's own
#: lookup from those two, and are kept for the operator to check it against.
DIRECTOR_KEYS = ("ad", "soyadi", "atasinin_adi", "fin", "seriya_nomresi")


class SettingsWriteError(RuntimeError):
    """The edit was refused or could not be completed — message fit for a banner."""


# A single ``key: value  # comment`` line. The quoted alternatives come first so
# a value containing '#' is taken as part of the scalar rather than read as the
# start of a comment. The bare alternative is lazy so trailing whitespace stays
# in the tail, where it is reproduced verbatim.
_KEY_LINE = re.compile(
    r"""^(?P<lead>[ \t]*)
         (?P<key>[A-Za-z_][A-Za-z0-9_]*)
         [ \t]*:[ \t]*
         (?P<value>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^#\r\n]*?)
         (?P<tail>[ \t]*(?:\#[^\r\n]*)?)
         (?P<eol>\r?\n?)$""",
    re.VERBOSE)

_PORTAL = re.compile(r"^portal[ \t]*:[ \t]*(?:\#.*)?\r?\n?$")
_DIRECTOR = re.compile(r"^(?P<lead>[ \t]+)director[ \t]*:[ \t]*(?:\#.*)?\r?\n?$")


def read_director(path: Path) -> dict[str, str]:
    """Read ``portal.director`` through the YAML parser.

    Reading is the easy direction and the parser should own it — this is the
    same load the pipeline does, so what comes back is what the uploader will
    see. Every key in :data:`DIRECTOR_KEYS` is present in the result; a key the
    file does not have reads as ``""``, which is exactly how
    ``assert_director_configured`` treats it.
    """
    import yaml

    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError) as exc:
        raise SettingsWriteError(f"Could not read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SettingsWriteError(f"{path} is not valid YAML: {exc}") from exc

    director = ((raw.get("portal") or {}).get("director") or {}) if isinstance(raw, dict) else {}
    if not isinstance(director, dict):
        director = {}
    return {key: _as_text(director.get(key)) for key in DIRECTOR_KEYS}


def write_director(path: Path, values: dict[str, str]) -> None:
    """Rewrite the director's values, leaving the rest of the file untouched.

    Every byte outside the five value spans survives, including the per-key
    inline comments (``ad: "TEST"   # (ad/name) — given name``) and the block
    of commentary above them.
    """
    path = Path(path)
    unknown = sorted(set(values) - set(DIRECTOR_KEYS))
    if unknown:
        raise SettingsWriteError(f"Not director fields: {', '.join(unknown)}")

    clean = {key: _validated(key, values[key]) for key in values}

    try:
        # newline="" disables universal-newline translation. Without it Python
        # hands back a file whose CRLFs have already become LFs, and writing
        # that out turns a one-line edit into a whole-file line-ending diff.
        with path.open(encoding="utf-8", newline="") as handle:
            original = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise SettingsWriteError(f"Could not read {path}: {exc}") from exc

    # keepends, so each line carries its own terminator through unchanged.
    lines = original.splitlines(keepends=True)
    start, end, indent = _locate_director(lines, path)
    updated = _rewrite(lines, start, end, indent, clean)

    if updated == lines:
        return          # nothing changed; do not churn the file or the backup

    backup = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        raise SettingsWriteError(f"Could not back up {path}: {exc}") from exc

    _atomic_write(path, "".join(updated))
    _verify(path, backup, clean)


# --------------------------------------------------------------------- parsing --
def _locate_director(lines: list[str], path: Path) -> tuple[int, int, str]:
    """Find the director block: (first key line, one past the last, indent).

    Located structurally rather than by searching for ``director:`` anywhere,
    because a key of that name under some other top-level block would be a
    different director. Anything that does not match this shape raises — writing
    into a file we have misread is the one outcome worth failing to avoid.
    """
    portal = next((i for i, line in enumerate(lines) if _PORTAL.match(line)), None)
    if portal is None:
        raise SettingsWriteError(
            f"{path.name}: no top-level 'portal:' block — refusing to guess where "
            f"the director's credentials belong.")

    director = None
    for index in range(portal + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line[:1].isspace():
            break                       # next top-level key: out of portal:
        match = _DIRECTOR.match(line)
        if match:
            director = index
            director_indent = match.group("lead")
            break
    if director is None:
        raise SettingsWriteError(
            f"{path.name}: 'portal:' has no 'director:' block to edit.")

    end = director + 1
    indent = director_indent + "  "
    for index in range(director + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            break                       # a blank line closes the block
        lead = line[:len(line) - len(line.lstrip())]
        if len(lead.expandtabs()) <= len(director_indent.expandtabs()):
            break                       # dedented back out of the block
        if end == director + 1:
            indent = lead               # take the block's real indent from it
        end = index + 1

    return director + 1, end, indent


def _rewrite(lines: list[str], start: int, end: int, indent: str,
             values: dict[str, str]) -> list[str]:
    """Return a new line list with the given keys' values replaced or appended."""
    updated = list(lines)
    remaining = dict(values)

    for index in range(start, end):
        match = _KEY_LINE.match(updated[index])
        if not match or match.group("key") not in remaining:
            continue
        key = match.group("key")
        updated[index] = (f"{match.group('lead')}{key}: {_quote(remaining.pop(key))}"
                          f"{match.group('tail')}{match.group('eol')}")

    if remaining:
        # A key the file never had. Appended in DIRECTOR_KEYS order at the
        # block's own indent rather than dropped: silently discarding a value
        # the user typed into a field is the worse failure.
        eol = _line_ending(updated, end)
        appended = [f"{indent}{key}: {_quote(remaining[key])}{eol}"
                    for key in DIRECTOR_KEYS if key in remaining]
        updated[end:end] = appended

    return updated


def _line_ending(lines: list[str], end: int) -> str:
    """The file's line ending, read off the block rather than assumed."""
    for line in reversed(lines[:end]):
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return os.linesep


# --------------------------------------------------------------------- values --
def _as_text(value) -> str:
    """A YAML scalar as the string the form shows.

    ``None`` is an empty key (``fin:`` with nothing after it), which is blank,
    not the word "None". Numbers matter too: a serial of ``09999901`` is quoted
    in the file, but an unquoted one would arrive as an int and must not reach
    the field as ``9999901``.
    """
    if value is None:
        return ""
    return str(value)


def _validated(key: str, value: str) -> str:
    """Refuse values that cannot be a name or an identity number."""
    text = _as_text(value).strip()
    if any(ch == "\n" or ch == "\r" or ord(ch) < 0x20 for ch in text):
        raise SettingsWriteError(
            f"'{key}' contains a line break or control character — that is a "
            f"paste accident, not a name.")
    return text


def _quote(value: str) -> str:
    """Always double-quoted, so ``09999901`` stays a string and not an octal-ish int."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------- write --
def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then replace.

    Same directory because ``os.replace`` is only atomic within a filesystem,
    and a settings file half-written by a crash mid-save is precisely the state
    this is here to make impossible.
    """
    try:
        fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name,
                                    suffix=".tmp")
    except OSError as exc:
        raise SettingsWriteError(f"Could not write {path}: {exc}") from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError as exc:
        # The temp file is ours and nothing has seen it; leaving it behind would
        # litter config/ with half-written settings look-alikes.
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise SettingsWriteError(f"Could not write {path}: {exc}") from exc


def _verify(path: Path, backup: Path, expected: dict[str, str]) -> None:
    """Read the file back; restore the backup if it is not what we meant.

    The write above is a text edit, not a serialisation, so nothing else
    guarantees the result parses. This is that guarantee.
    """
    try:
        written = read_director(path)
    except SettingsWriteError as exc:
        _restore(path, backup)
        raise SettingsWriteError(
            f"The edited settings file no longer parses ({exc}) — the previous "
            f"version has been restored.") from None

    wrong = {key: value for key, value in expected.items() if written.get(key) != value}
    if wrong:
        _restore(path, backup)
        raise SettingsWriteError(
            f"The edit did not land as written ({', '.join(sorted(wrong))}) — the "
            f"previous version has been restored.")


def _restore(path: Path, backup: Path) -> None:
    """Put the backup back. Never raises: it runs while another error is in flight."""
    try:
        shutil.copy2(backup, path)
    except OSError:
        pass
