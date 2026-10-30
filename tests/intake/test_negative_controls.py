"""Negative controls for the path globs (#103): every `money_paths` glob and every repo's
`ladder_pinned_paths` glob has a near-miss path that must not match, checked with the
function the glob is really used with.

- `money_paths` are detection globs: `matches` / `matches_any` (loose: a glob without `/`
  is a basename anywhere, one with `/` matches the path's tail, case-insensitive). The call
  sites are `router.rules._rule` (rule 2), `_pinned_hit`, `review.ladder` shape detection
  and `packets.prefill`.
- `ladder_pinned_paths` are scope globs: strict `in_scope` (anchored, case-sensitive,
  `*` inside a segment). The call sites are `review.ladder.Ladder.pinned`,
  `router.rules._pinned_hit` and `packets.prefill`.

The tables are data on purpose: the meta-tests load the real config and fail a glob that
has no negative here, so a new glob cannot ship without a near-miss.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from vigild import config as config_mod
from vigild.intake.paths import in_scope, matches

# glob -> (paths it must match, near-miss paths it must not). Loose `matches`.
MONEY: dict[str, tuple[list[str], list[str]]] = {
    "src/billing/**": (
        ["src/billing/fee.py", "server/src/billing/x/y.ts", "SRC/Billing/Fee.py"],
        ["src/billingx/fee.py", "mysrc/billing/fee.py", "src/billing.py", "lib/billing/fee.py"],
    ),
    "src/auth/**": (
        ["src/auth/login.py", "web/src/auth/session.ts"],
        ["src/authz/login.py", "lib/auth/login.py", "src/auth.py", "xsrc/auth/login.py"],
    ),
    "**/payments/**": (
        ["a/payments/b.py", "payments/b.py"],
        ["a/payment/b.py", "a/payments.py", "a/mypayments/b.py", "docs/payments.md"],
    ),
    "**/consent/**": (
        ["app/consent/banner.py", "consent/a.py"],
        ["app/consents/banner.py", "app/consent.py", "app/inconsent/banner.py"],
    ),
    "**/stripe*": (
        ["src/stripe/webhook.py", "stripe_client.py", "pkg/Stripe.py"],
        ["src/mystripe/webhook.py", "src/strip/webhook.py", "src/payments_stripped.py"],
    ),
    "**/wallet/**": (
        ["app/wallet/pass.py", "wallet/a.py"],
        ["app/wallets/pass.py", "app/wallet.py", "app/mywallet/pass.py"],
    ),
    "fly.toml": (
        ["fly.toml", "deploy/fly.toml", "Fly.TOML"],
        ["fly.tomlx", "myfly.toml", "fly.toml.md", "fly.yaml"],
    ),
    "*Config.xcconfig": (
        ["Config.xcconfig", "ios/ReleaseConfig.xcconfig", "ios/DEBUGCONFIG.XCCONFIG"],
        ["Config.xcconfig.bak", "ios/Config.xcconfigs", "ios/Config.plist", "ios/Config.xcconf"],
    ),
}

# glob -> (paths it must match, near-miss paths it must not). Strict `in_scope`.
PINNED: dict[str, dict[str, tuple[list[str], list[str]]]] = {
    "thomasbardhi01/vigil": {
        "vigild/gateway/**": (
            ["vigild/gateway/service.py", "vigild/gateway/a/b.py"],
            [
                "vigild/gatewayx/service.py",
                "src/vigild/gateway/service.py",
                "Vigild/Gateway/service.py",
                "vigild/gateway.py",
                "tests/gateway/test_service.py",
            ],
        ),
        "vigild/budget.py": (
            ["vigild/budget.py"],
            ["vigild/budgets.py", "vigild/budget.pyc", "vigild/Budget.py", "x/vigild/budget.py"],
        ),
        "vigild/metering/**": (
            ["vigild/metering/meter.py", "vigild/metering/a/b.py"],
            ["vigild/meteringx/meter.py", "vigild/meter/meter.py", "src/vigild/metering/meter.py"],
        ),
        "configs/budgets.yaml": (
            ["configs/budgets.yaml"],
            [
                "configs/budgets.yml",
                "configs/budgets.yaml.bak",
                "config/budgets.yaml",
                "x/configs/budgets.yaml",
                "Configs/budgets.yaml",
            ],
        ),
        "docs/owner-rulings.md": (
            ["docs/owner-rulings.md"],
            [
                "docs/owner-rulings.md.bak",
                "docs/owner-ruling.md",
                "docs/Owner-Rulings.md",
                "x/docs/owner-rulings.md",
            ],
        ),
        "vigild/review/ladder.py": (
            ["vigild/review/ladder.py"],
            [
                "vigild/review/ladders.py",
                "vigild/review/ladder.pyi",
                "vigild/ladder.py",
                "vigild/review/sub/ladder.py",
            ],
        ),
    },
}


def _money_rows() -> Iterator[tuple[str, str, bool]]:
    for glob, (pos, neg) in MONEY.items():
        yield from ((glob, p, True) for p in pos)
        yield from ((glob, p, False) for p in neg)


def _pinned_rows() -> Iterator[tuple[str, str, str, bool]]:
    for repo, globs in PINNED.items():
        for glob, (pos, neg) in globs.items():
            yield from ((repo, glob, p, True) for p in pos)
            yield from ((repo, glob, p, False) for p in neg)


@pytest.mark.parametrize("glob,path,expected", list(_money_rows()))
def test_money_glob_loose_matching(glob: str, path: str, expected: bool) -> None:
    assert matches(path, glob) is expected


@pytest.mark.parametrize("repo,glob,path,expected", list(_pinned_rows()))
def test_pinned_glob_strict_matching(repo: str, glob: str, path: str, expected: bool) -> None:
    assert in_scope(path, [glob]) is expected


def test_a_pinned_near_miss_is_not_saved_by_the_loose_rules() -> None:
    """The pinned globs are strict, not loose: the tail-match that flags a money path
    (`server/src/billing/x` for `src/billing/**`) must not widen a pin."""
    assert matches("x/vigild/budget.py", "vigild/budget.py")  # detection is loose
    assert not in_scope("x/vigild/budget.py", ["vigild/budget.py"])  # scope is strict


# --- the meta-test: the real config against the tables -------------------------------------


def test_every_configured_glob_has_a_negative_and_a_positive() -> None:
    cfg = config_mod.load()
    problems: list[str] = []
    for glob in cfg.routing.money_paths:
        pos, neg = MONEY.get(glob, ([], []))
        if not neg:
            problems.append(f"money_paths {glob!r}: no near-miss in MONEY")
        if not pos:
            problems.append(f"money_paths {glob!r}: no positive control in MONEY")
    for repo, pol in cfg.repos.repos.items():
        for glob in pol.ladder_pinned_paths:
            pos, neg = PINNED.get(repo, {}).get(glob, ([], []))
            if not neg:
                problems.append(f"{repo} ladder_pinned_paths {glob!r}: no near-miss in PINNED")
            if not pos:
                problems.append(f"{repo} ladder_pinned_paths {glob!r}: no positive in PINNED")
    assert not problems, "add a case to the tables in this file:\n" + "\n".join(problems)


def test_the_tables_hold_no_glob_the_config_dropped() -> None:
    cfg = config_mod.load()
    stale = [g for g in MONEY if g not in cfg.routing.money_paths]
    for repo, globs in PINNED.items():
        pins = cfg.repos.repos[repo].ladder_pinned_paths if repo in cfg.repos.repos else []
        stale += [f"{repo}: {g}" for g in globs if g not in pins]
    assert not stale, f"cases for globs no longer configured: {stale}"


def test_negatives_are_at_least_the_positives() -> None:
    money_pos = sum(len(p) for p, _ in MONEY.values())
    money_neg = sum(len(n) for _, n in MONEY.values())
    pin_pos = sum(len(p) for g in PINNED.values() for p, _ in g.values())
    pin_neg = sum(len(n) for g in PINNED.values() for _, n in g.values())
    assert money_neg >= money_pos, (money_neg, money_pos)
    assert pin_neg >= pin_pos, (pin_neg, pin_pos)
    assert money_neg + pin_neg >= money_pos + pin_pos
