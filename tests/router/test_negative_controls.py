"""Negative controls for the routing rules (#103): every rule has a near-miss that must
not match it, and a meta-test fails a rule that has none.

How each is reached (owner, 2026-10-28: a routing test submits a request and never sets
the input the rule reads, #100):

- coord rules `architecture`, `tests-docs`, `pinned` and `default`: end to end, a request
  POSTed to `/api/jobs` with the `world` fixture, the way `tests/jobs/test_coord_routing.py`
  does. The coord's recorded reason is what is checked.
- coord rules `escalation` and `fix-small`: IN-PROCESS only (`route_coord(CoordShape)`),
  like `test_coord_rules.py`. The attempt is derived from replan events and a size comes
  from a vigild estimate that does not exist yet; `POST /api/jobs` carries neither, and
  `JobRequest` forbids extra fields.
- task rules 1-9 (`route(Task)`): IN-PROCESS only, like `test_rules.py`. A task's tier is
  chosen while the runner plans a job (`_reroute`, plan intake), and the API returns no
  route, so no request reaches these rules short of a full coord run.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.conftest import auth
from tests.jobs.test_coord_loop import REPO, World, _request, world  # noqa: F401
from tests.router.test_rules import _t
from vigild import config as config_mod
from vigild.config import Config
from vigild.contract.models import Size
from vigild.router import rules
from vigild.router.rules import CoordShape, route, route_coord

VIGIL = "thomasbardhi01/vigil"
ALWAYS_RULES = {"rule9", "default"}  # a rule that always matches cannot have a near-miss


# --- task rules 1-9 (in-process) ----------------------------------------------------------


@dataclass(frozen=True)
class TaskCase:
    rule: str  # "rule3": the rule under test
    note: str
    positive: bool  # True: the rule must fire; False: it must not, and `lands` must
    kw: dict[str, Any]
    lands: str  # the tier_reason prefix the task ends up with
    route_kw: dict[str, Any] = field(default_factory=dict)


def _c(rule: str, note: str, positive: bool, lands: str, **kw: Any) -> TaskCase:
    route_kw = {"override_tier": kw.pop("override_tier")} if "override_tier" in kw else {}
    return TaskCase(rule, note, positive, kw, lands, route_kw)


def _files(*f: str) -> dict[str, Any]:
    return {"files_in_scope": list(f)}


TASK_CASES: list[TaskCase] = [
    # rule 1: no test_cmd or no done_when
    _c("rule1", "no test_cmd", True, "rule1", spec={"test_cmd": None}),
    _c("rule1", "blank done_when", True, "rule1", spec={"done_when": "  "}),
    _c(
        "rule1",
        "one-character test_cmd and done_when",
        False,
        "rule9",
        spec={"test_cmd": "t", "done_when": "d"},
    ),
    _c("rule1", "both present, label docs", False, "rule9", labels=["docs"]),
    # rule 2: a money path in scope
    _c(
        "rule2", "tail match under server/", True, "rule2", spec=_files("server/src/billing/fee.ts")
    ),
    _c("rule2", "billing-prefixed directory", False, "rule9", spec=_files("src/billingx/fee.py")),
    _c("rule2", "auth under another root", False, "rule9", spec=_files("lib/auth/login.py")),
    _c("rule2", "payments as a file name", False, "rule9", spec=_files("docs/payments.md")),
    _c("rule2", "wallets directory", False, "rule9", spec=_files("app/wallets/pass.py")),
    _c("rule2", "fly.toml near miss", False, "rule9", spec=_files("fly.tomlx")),
    _c(
        "rule2",
        "tier override is fine off a money path",
        False,
        "override:",
        spec=_files("docs/a.md"),
        override_tier="local",
    ),
    _c(
        "rule2",
        "local-ok is fine off a money path",
        False,
        "rule9",
        labels=["vigil:local-ok"],
        spec=_files("docs/a.md"),
    ),
    # rule 3: architecture labels
    _c("rule3", "architecture", True, "rule3", labels=["architecture"]),
    _c("rule3", "migration", True, "rule3", labels=["migration"]),
    _c("rule3", "a letter short", False, "rule9", labels=["architectur"]),
    _c("rule3", "plural", False, "rule9", labels=["migrations"]),
    _c("rule3", "different case", False, "rule9", labels=["Architecture"]),
    _c(
        "rule3",
        "architecture.md in scope is not the label",
        False,
        "rule9",
        spec=_files("docs/architecture.md"),
    ),
    # rule 4: a feature with no existing tests (False, not unknown)
    _c("rule4", "feature, no tests", True, "rule4", labels=["feature"], has_existing_tests=False),
    _c("rule4", "feature, tests unknown", False, "rule9", labels=["feature"]),
    _c("rule4", "feature, has tests", False, "rule9", labels=["feature"], has_existing_tests=True),
    _c(
        "rule4", "features, no tests", False, "rule9", labels=["features"], has_existing_tests=False
    ),
    _c("rule4", "no feature label, no tests", False, "rule9", has_existing_tests=False),
    # rule 5: attempt >= 3 or review_rounds >= 2
    _c("rule5", "attempt 3", True, "rule5", attempt=3),
    _c("rule5", "review round 2", True, "rule5", review_rounds=2),
    _c("rule5", "attempt 2", False, "rule9", attempt=2),
    _c("rule5", "review round 1", False, "rule9", review_rounds=1),
    # rule 6: a local label, size S or M, tests in scope
    _c(
        "rule6",
        "tests, S, has tests",
        True,
        "rule6",
        labels=["tests"],
        size="S",
        has_existing_tests=True,
    ),
    _c(
        "rule6",
        "tests, M, has tests",
        True,
        "rule6",
        labels=["tests"],
        size="M",
        has_existing_tests=True,
    ),
    _c("rule6", "size L", False, "rule9", labels=["tests"], size="L", has_existing_tests=True),
    _c("rule6", "size XS", False, "rule9", labels=["tests"], size="XS", has_existing_tests=True),
    _c(
        "rule6",
        "label one letter off",
        False,
        "rule9",
        labels=["test"],
        size="S",
        has_existing_tests=True,
    ),
    _c(
        "rule6",
        "tests not in scope",
        False,
        "rule9",
        labels=["tests"],
        size="S",
        has_existing_tests=False,
    ),
    _c("rule6", "tests unknown", False, "rule9", labels=["tests"], size="S"),
    _c("rule6", "no size", False, "rule9", labels=["tests"], has_existing_tests=True),
    # rule 7: size XS and only xs labels
    _c("rule7", "XS docs", True, "rule7", labels=["docs"], size="XS"),
    _c("rule7", "XS lint", True, "rule7", labels=["lint"], size="XS"),
    _c(
        "rule7",
        "S docs with tests goes to rule 6",
        False,
        "rule6",
        labels=["docs"],
        size="S",
        has_existing_tests=True,
    ),
    _c("rule7", "XS docs plus tests", False, "rule9", labels=["docs", "tests"], size="XS"),
    _c("rule7", "XS no labels", False, "rule9", size="XS"),
    _c("rule7", "label one letter off", False, "rule9", labels=["doc"], size="XS"),
    _c("rule7", "XS but a non-xs label", False, "rule9", labels=["deps"], size="XS"),
    # rule 8: review-followup and size S
    _c("rule8", "review-followup S", True, "rule8", labels=["review-followup"], size="S"),
    _c("rule8", "size M", False, "rule9", labels=["review-followup"], size="M"),
    _c("rule8", "size XS", False, "rule9", labels=["review-followup"], size="XS"),
    _c("rule8", "label plural", False, "rule9", labels=["review-followups"], size="S"),
    _c("rule8", "label hyphenated", False, "rule9", labels=["review-follow-up"], size="S"),
    # rule 9 is the default: it always matches, so it has no near-miss (ALWAYS_RULES).
]


@pytest.mark.parametrize(
    "case",
    TASK_CASES,
    ids=[f"{c.rule}-{'pos' if c.positive else 'neg'}-{c.note}" for c in TASK_CASES],
)
def test_task_rule_cases(cfg: Config, case: TaskCase) -> None:
    got = route(_t(**case.kw), cfg, **case.route_kw).tier_reason
    assert got.startswith(case.lands), got
    assert got.startswith(case.rule) is case.positive, got


# --- coord rules ----------------------------------------------------------------------------


@dataclass(frozen=True)
class CoordCase:
    rule: str  # the coord rule's name under test
    note: str
    positive: bool
    lands: str  # the rule that actually wins
    how: str  # "request": POST /api/jobs; "shape": in-process CoordShape
    labels: tuple[str, ...] = ()
    text: str = ""  # request: a sentence that may name a path
    shape: dict[str, Any] = field(default_factory=dict)  # shape: extra CoordShape fields
    pins: bool = True  # request: the repo carries vigil's real ladder_pinned_paths


def _r(
    rule: str, note: str, pos: bool, lands: str, *labels: str, text: str = "", pins: bool = True
) -> CoordCase:
    return CoordCase(rule, note, pos, lands, "request", labels, text, pins=pins)


def _s(rule: str, note: str, pos: bool, lands: str, *labels: str, **shape: Any) -> CoordCase:
    return CoordCase(rule, note, pos, lands, "shape", labels, shape=shape)


COORD_CASES: list[CoordCase] = [
    # escalation: attempt >= 3 (in-process; see the module docstring)
    _s("escalation", "attempt 3", True, "escalation", "tests", attempt=3),
    _s("escalation", "attempt 2", False, "tests-docs", "tests", attempt=2),
    _s("escalation", "attempt 1", False, "tests-docs", "docs", attempt=1),
    _r("escalation", "a fresh request is attempt 1", False, "tests-docs", "docs"),
    # architecture
    _r("architecture", "architecture", True, "architecture", "docs", "architecture"),
    _r("architecture", "migration", True, "architecture", "migration"),
    _r("architecture", "a letter short", False, "tests-docs", "docs", "architectur"),
    _r("architecture", "plural", False, "tests-docs", "docs", "migrations"),
    _r("architecture", "different case", False, "tests-docs", "docs", "Architecture"),
    _r(
        "architecture",
        "architecture.md named in the text",
        False,
        "tests-docs",
        "docs",
        text="Fix a typo in `docs/architecture.md`.",
    ),
    # pinned: a named path in the repo's ladder_pinned_paths (strict) or money_paths (loose)
    _r("pinned", "pinned file", True, "pinned", "docs", text="Edit `vigild/gateway/service.py`."),
    _r("pinned", "money path", True, "pinned", "docs", text="Edit `src/billing/fee.py`."),
    _r(
        "pinned",
        "directory one letter off",
        False,
        "tests-docs",
        "docs",
        text="Edit `vigild/gatewayx/service.py`.",
    ),
    _r(
        "pinned",
        "shared prefix, other directory",
        False,
        "tests-docs",
        "docs",
        text="Edit `vigild/gateway_notes/a.py`.",
    ),
    _r(
        "pinned",
        "pinned file under another root",
        False,
        "tests-docs",
        "docs",
        text="Edit `src/vigild/budget.py`.",
    ),
    _r(
        "pinned",
        "file name one letter off",
        False,
        "tests-docs",
        "docs",
        text="Edit `vigild/budgets.py`.",
    ),
    _r(
        "pinned",
        "pinned file in a repo that pins nothing",
        False,
        "tests-docs",
        "docs",
        text="Edit `vigild/gateway/service.py`.",
        pins=False,
    ),
    _r(
        "pinned", "money near miss", False, "tests-docs", "docs", text="Edit `src/billingx/fee.py`."
    ),
    _r(
        "pinned",
        "money glob under another root",
        False,
        "tests-docs",
        "docs",
        text="Edit `mysrc/auth/login.py`.",
    ),
    _r(
        "pinned",
        "wildcard hint that cannot name a pinned file",
        False,
        "tests-docs",
        "docs",
        text="Touch `docs/*.txt`.",
    ),
    _r(
        "pinned",
        "wildcard hint that can name the rulings file",
        True,
        "pinned",
        "docs",
        text="Touch `docs/*.md`.",
    ),
    # tests-docs
    _r("tests-docs", "tests", True, "tests-docs", "tests"),
    _r("tests-docs", "docs", True, "tests-docs", "docs"),
    _r("tests-docs", "singular", False, "default", "test"),
    _r("tests-docs", "a letter short", False, "default", "doc"),
    _r("tests-docs", "different case", False, "default", "Docs"),
    # fix-small: a fix with a size of S or M (in-process; see the module docstring)
    _s("fix-small", "fix S", True, "fix-small", "fix", size=Size.S),
    _s("fix-small", "fix M", True, "fix-small", "fix", size=Size.M),
    _s("fix-small", "one step over", False, "default", "fix", size=Size.L),
    _s("fix-small", "one step under", False, "default", "fix", size=Size.XS),
    _s("fix-small", "no size", False, "default", "fix"),
    _s("fix-small", "label one letter off", False, "default", "fixx", size=Size.S),
    _s("fix-small", "S but not a fix", False, "default", size=Size.S),
    _s(
        "fix-small",
        "a parent job makes it a fix",
        True,
        "fix-small",
        size=Size.S,
        parent_job_id="vi-0001",
    ),
    _r("fix-small", "a request carries no size", False, "default", "fix"),
    # default is `when: always`: it has no near-miss (ALWAYS_RULES).
]


def _id(c: CoordCase) -> str:
    return f"{c.rule}-{'pos' if c.positive else 'neg'}-{c.note}"


def _reason_rule(reason: str) -> str:
    m = re.match(r"coord:rule-([\w-]+)", reason)
    assert m, reason
    return m.group(1)


@pytest.mark.parametrize(
    "case",
    [c for c in COORD_CASES if c.how == "shape"],
    ids=[_id(c) for c in COORD_CASES if c.how == "shape"],
)
def test_coord_rule_cases_in_process(cfg: Config, case: CoordCase) -> None:
    shape = CoordShape(labels=list(case.labels), **case.shape)
    got = _reason_rule(route_coord(cfg, VIGIL, shape).reason)
    assert got == case.lands
    assert (got == case.rule) is case.positive


@pytest.mark.parametrize(
    "case",
    [c for c in COORD_CASES if c.how == "request"],
    ids=[_id(c) for c in COORD_CASES if c.how == "request"],
)
def test_coord_rule_cases_by_request(world: World, case: CoordCase) -> None:  # noqa: F811
    pins = config_mod.load().repos.repos[VIGIL].ladder_pinned_paths
    world.runner.cfg.repos.repos[REPO].ladder_pinned_paths = list(pins) if case.pins else []
    r = world.client.post(
        "/api/jobs",
        headers=auth(world.tokens.admin),
        json={
            "repo": REPO,
            "title": "Document the rate limit",
            "request": f"The limit is undocumented. {case.text}".strip(),
            "why": "support asks weekly",
            "value": 3,
            "risk": 1,
            "labels": list(case.labels),
        },
    )
    assert r.status_code == 202, r.text
    from vigild.jobs.model import Role

    coord = [s for s in world.store.list_sessions(r.json()["id"]) if s.role is Role.COORD][-1]
    got = _reason_rule(coord.detail["coord_reason"])
    assert got == case.lands, coord.detail["coord_reason"]
    assert (got == case.rule) is case.positive


def test_a_plain_request_is_not_escalated_or_pinned(world: World) -> None:  # noqa: F811
    job = _request(world)
    from vigild.jobs.model import Role

    coord = [s for s in world.store.list_sessions(job) if s.role is Role.COORD][-1]
    assert _reason_rule(coord.detail["coord_reason"]) == "default"


# --- the meta-tests: the real rules against the tables -------------------------------------


def _task_rule_ids() -> set[str]:
    return set(re.findall(r"\"(rule\d+):", inspect.getsource(rules._rule)))


def test_the_task_rules_are_the_ones_the_table_knows() -> None:
    ids = _task_rule_ids()
    assert ids == {f"rule{n}" for n in range(1, 10)}, ids  # a new rule: add its cases


def test_every_task_rule_has_a_positive_and_a_negative() -> None:
    problems = []
    for rule in sorted(_task_rule_ids() - ALWAYS_RULES):
        pos = [c for c in TASK_CASES if c.rule == rule and c.positive]
        neg = [c for c in TASK_CASES if c.rule == rule and not c.positive]
        if not pos:
            problems.append(f"{rule}: no positive case")
        if not neg:
            problems.append(f"{rule}: no near-miss case")
    assert not problems, "add cases to TASK_CASES:\n" + "\n".join(problems)


def test_every_coord_rule_has_a_positive_and_a_negative() -> None:
    cfg = config_mod.load()
    problems = []
    for rule in cfg.routing.coord:
        if rule.when == "always":
            assert rule.name in ALWAYS_RULES, f"{rule.name}: an always rule must be the default"
            continue
        pos = [c for c in COORD_CASES if c.rule == rule.name and c.positive]
        neg = [c for c in COORD_CASES if c.rule == rule.name and not c.positive]
        if not pos:
            problems.append(f"{rule.name}: no positive case")
        if not neg:
            problems.append(f"{rule.name}: no near-miss case")
    assert not problems, "add cases to COORD_CASES:\n" + "\n".join(problems)


def test_the_tables_name_no_rule_that_is_gone() -> None:
    cfg = config_mod.load()
    assert {c.rule for c in COORD_CASES} <= {r.name for r in cfg.routing.coord}
    assert {c.rule for c in TASK_CASES} <= _task_rule_ids()


def test_negatives_are_at_least_the_positives() -> None:
    for table in (TASK_CASES, COORD_CASES):
        pos = sum(1 for c in table if c.positive)
        neg = sum(1 for c in table if not c.positive)
        assert neg >= pos, (neg, pos)
