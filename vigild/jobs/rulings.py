"""The owner's rulings index (`docs/owner-rulings.md`) as the coord token's gate (#146).

A coord approval, and a coord note on a replan or a fix, must cite a ruling that contains
one `## ` heading of that file verbatim. vigild reads the file from its **mirror of
origin/main** (`Workspace.mirror_file`), never from the checkout it runs from: a coord
session can edit that working tree without a PR (owner, 2026-10-30). A mirror that can't
be read refuses every such call (fail closed). The matched heading is recorded beside the
ruling text.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

RULINGS_REPO = "thomasbardhi01/vigil"
RULINGS_FILE = "docs/owner-rulings.md"
NOTE_LABEL = "coord's note (ruling: "

Source = Callable[[], str | None]


class RulingError(ValueError):
    """The ruling is not usable; the message says why and lists the valid headings."""


class _Mirror(Protocol):
    def mirror_file(self, repo: str, branch: str, path: str) -> str | None: ...


def from_mirror(ws: _Mirror) -> Source:
    """The rulings file as it is on main in vigild's mirror (None if it can't be read)."""
    return lambda: ws.mirror_file(RULINGS_REPO, "main", RULINGS_FILE)


def headings(text: str | None) -> list[str]:
    if text is None:
        raise RulingError(
            f"{RULINGS_FILE} on main can't be read from vigild's mirror; coord rulings are refused"
        )
    return [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]


def match(ruling: str, text: str | None) -> str:
    """The first heading (file order) of `text` (the file on main) that `ruling` contains
    verbatim."""
    found = headings(text)
    for h in found:
        if h and h in ruling:
            return h
    raise RulingError(
        f"the ruling must contain a heading of {RULINGS_FILE} on main verbatim: "
        + "; ".join(f"`{h}`" for h in found)
    )


def label_note(note: str, heading: str) -> str:
    """A coord's note as it is stored and shown: labelled as the coord's, with its ruling."""
    return f"{NOTE_LABEL}{heading})\n\n{note}"


def is_coord_note(note: str) -> bool:
    return note.startswith(NOTE_LABEL)
