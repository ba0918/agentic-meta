#!/usr/bin/env python3
"""Which stores a run reads, where it reads each one, and whether each is there.

Two entry points need the same three adapters, built the same way and pointed at
the same locations. Building them in each entry point would let the two drift into
reading different things under the same argument, so the choice is made here once
and each entry point only says which stores it wants.

Every adapter is registered by the name its own module declares, and a run's
selection is resolved against that registry. Adding a store is adding an entry:
neither entry point mentions a store by name, and neither has to change.

A location that does not exist is not an error and not a silence. The adapters
already read an absent location as an empty store — an operator may simply not run
that runtime — so the reading returns the store anyway and says it was not there.
Reporting the absence is the caller's job; losing it is nobody's.
"""

import dataclasses
import datetime
import pathlib
import typing

import store_claude
import store_codex
import store_opencode
from events import SessionStore

# The selection standing for every registered store.
EVERY_STORE = "all"


def _claude(
    location: pathlib.Path, since: datetime.datetime | None, project: str | None
) -> SessionStore:
    return store_claude.ClaudeCodeStore(root=location, since=since, project=project)


def _opencode(
    location: pathlib.Path, since: datetime.datetime | None, project: str | None
) -> SessionStore:
    return store_opencode.OpenCodeStore(db_path=location, since=since, project=project)


def _codex(
    location: pathlib.Path, since: datetime.datetime | None, project: str | None
) -> SessionStore:
    return store_codex.CodexStore(root=location, since=since, project=project)


def _is_directory(location: pathlib.Path) -> bool:
    return location.is_dir()


def _is_file(location: pathlib.Path) -> bool:
    return location.is_file()


@dataclasses.dataclass(frozen=True)
class StoreKind:
    """One registered store: its name, where it lives, how it is built and found.

    Presence is asked per kind rather than by one rule, because a store kept as a
    directory of logs and a store kept as one database file are absent in
    different ways, and a single rule would call one of them present when it is not.

    The command-line argument that points the store elsewhere is registered here
    too. It is the entry points that parse it, but a store has exactly one such
    argument, and holding the name beside the store is what keeps two entry points
    from spelling it two ways — or from having to be edited at all when a store is
    added.
    """

    name: str
    location_flag: str
    default_location: typing.Callable[[], pathlib.Path]
    build: typing.Callable[
        [pathlib.Path, datetime.datetime | None, str | None], SessionStore
    ]
    exists: typing.Callable[[pathlib.Path], bool]


REGISTRY = (
    StoreKind(store_claude.NAME, "--claude-root", store_claude.default_root,
              _claude, _is_directory),
    StoreKind(store_opencode.NAME, "--opencode-db", store_opencode.default_db_path,
              _opencode, _is_file),
    StoreKind(store_codex.NAME, "--codex-root", store_codex.default_root,
              _codex, _is_directory),
)

STORE_NAMES = tuple(kind.name for kind in REGISTRY)
SELECTABLE = STORE_NAMES + (EVERY_STORE,)


@dataclasses.dataclass(frozen=True)
class Reading:
    """One store as this run will read it: built, located, and found or not found."""

    name: str
    store: SessionStore
    location: pathlib.Path
    present: bool


def given_locations(arguments: typing.Any) -> dict[str, str]:
    """The locations a command line named, keyed by store name.

    A store the command line said nothing about is left out rather than mapped to
    nothing, so building falls through to that store's own default.
    """
    named: dict[str, str] = {}
    for kind in REGISTRY:
        given = getattr(arguments, kind.location_flag.lstrip("-").replace("-", "_"), None)
        if given is not None:
            named[kind.name] = given
    return named


def selected_names(selection: str) -> tuple[str, ...]:
    """The stores one selection asks for, in the order they are registered.

    A name no store answers to is refused rather than read as an empty selection: a
    misspelt store would otherwise produce a report of no friction anywhere, which
    reads exactly like a clean measurement.
    """
    if selection == EVERY_STORE:
        return STORE_NAMES
    if selection not in STORE_NAMES:
        raise ValueError(f"no store is named {selection!r}")
    return (selection,)


def build_stores(
    selection: str,
    locations: dict[str, str | pathlib.Path] | None = None,
    since: datetime.datetime | None = None,
    project: str | None = None,
) -> list[Reading]:
    """Build every selected store, at the location given for it or at its default.

    A location given for a store that was not selected is ignored rather than
    refused: the entry points accept one location argument per store, and an
    operator who passes all of them while asking for one store has not made a
    mistake worth stopping for.
    """
    wanted = selected_names(selection)
    given = locations or {}
    built: list[Reading] = []
    for kind in REGISTRY:
        if kind.name not in wanted:
            continue
        override = given.get(kind.name)
        location = (
            pathlib.Path(override) if override is not None else kind.default_location()
        )
        built.append(
            Reading(
                name=kind.name,
                store=kind.build(location, since, project),
                location=location,
                present=kind.exists(location),
            )
        )
    return built
