"""The owner's rulings index (`docs/owner-rulings.md`) as the coord token's gate (#146).

A coord approval, and a coord note on a replan or a fix, must cite a ruling that contains
one `## ` heading of that file verbatim. vigild reads the file from the checkout it runs
from (relative to this package), never from a session's clone; an unreadable file refuses
every such call (fail closed). The matched heading is recorded beside the ruling text.
"""

from __future__ import annotations

from pathlib import Path

RULINGS_PATH = Path(__file__).resolve().parents[2] / "docs" / "owner-rulings.md"
NOTE_LABEL = "coord's note (ruling: "


class RulingError(ValueError):
    """The ruling is not usable; the message says why and lists the valid headings."""


def headings() -> list[str]:
    try:
        text = RULINGS_PATH.read_text()
    except OSError as e:
        raise RulingError("docs/owner-rulings.md is unreadable; coord rulings are refused") from e
    return [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]


def match(ruling: str) -> str:
    """The first heading (file order) that `ruling` contains verbatim."""
    found = headings()
    for h in found:
        if h and h in ruling:
            return h
    raise RulingError(
        "the ruling must contain a heading of docs/owner-rulings.md verbatim: "
        + "; ".join(f"`{h}`" for h in found)
    )


def label_note(note: str, heading: str) -> str:
    """A coord's note as it is stored and shown: labelled as the coord's, with its ruling."""
    return f"{NOTE_LABEL}{heading})\n\n{note}"


def is_coord_note(note: str) -> bool:
    return note.startswith(NOTE_LABEL)
