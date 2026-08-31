#!/usr/bin/env python3
"""Behaviour surface of a skill and the dependency graph over it.

The behaviour surface is the set of files that can affect a skill's run-time
behaviour:
  - every file under `skills/<name>/` (test_*.py, __pycache__ and *.pyc aside)
  - what that skill's own .md reaches in **one hop** through a relative link or
    a bare path in its procedural text, shared contracts included
  - what that skill's own .py imports from `skills/shared/scripts/`, again one hop
  - the own surface of every skill it is declared to read **by name** in
    `evals/dependencies.yml`, one hop: what those skills declare in turn is not
    followed

Editing one shared contract can change the behaviour of every skill citing it.
This reverse lookup — changed file to affected skill — is what a regression run
is selected by.

**Why one hop.** The traversal used to be an unbounded transitive closure, which
kept following the related-reading links between shared contracts until skills
whose execution paths never meet sat on the same surface: one skill reached
another three hops out through two shared contracts, and appending a section to
the far one marked the near one stale. Not traversing out of files that lie
outside the skill's own directory keeps the surface aligned with the
one-level-deep reference principle skill authoring already follows.

**Why a declaration for skills read by name.** A skill body may tell the agent
to read another skill and follow it, naming the skill rather than a path — a
convention some repositories require. No path ever matches, so without a
declaration the named skill's text can change and the reader's lock stays
green. The declaration is not scanned out of the body: skill bodies name their
siblings freely as related reading, and treating every mention as a dependency
would fuse the surfaces the one-hop rule exists to keep apart. It lives on the
evaluation side rather than in the skill's frontmatter because it exists for
the measurement, and nothing that measures a skill is written inside it. A
name on either side of a declaration that matches no skill refuses the whole
computation: a misspelt name that bought nothing and said nothing would reopen
the gap the declaration closes.

**What is deliberately outside the surface.** Verification and evaluation assets
live outside the skill directories — the lock at the repository root, scenarios
under `evals/`. Were they on the surface, recording a verification would change
the surface it was recorded against, and editing a scenario would mark its own
skill stale. Their placement is what prevents that, so no exclusion list is kept
here for them. The dependency declaration is such an asset too: on the
surface, declaring a dependency would itself mark the declaring skill stale.

CLI:
  python3 dep_graph.py [root]                   # every skill's surface, as JSON
  python3 dep_graph.py --impact FILE... [root]  # affected skill names, one per line
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import md_links  # noqa: E402
import yaml_subset  # noqa: E402

_EXCLUDED_DIR_NAMES = {"__pycache__"}

DEPENDENCIES_FILE = "evals/dependencies.yml"


class DependencyError(Exception):
    """The dependency declaration cannot be used as written."""


def _skill_names(root):
    """Every skill directory holding a SKILL.md, `shared` excluded."""
    base = os.path.join(root, "skills")
    return {name for name in os.listdir(base)
            if name != "shared" and os.path.isfile(os.path.join(base, name, "SKILL.md"))}


def _declares_nothing(text):
    return all(not line.strip() or line.lstrip().startswith("#")
               for line in text.splitlines())


def load_declared_dependencies(root):
    """{declaring skill: [skill names it reads by name]} from the evaluation side.

    Only an absent file means no declarations; a file that cannot be read is
    refused rather than read as empty, which would drop every declaration
    without a word. Names on either side that match no skill are refused too.
    """
    path = os.path.join(root, DEPENDENCIES_FILE.replace("/", os.sep))
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise DependencyError(f"{DEPENDENCIES_FILE}: cannot be read ({exc})") from exc
    if _declares_nothing(text):
        return {}
    try:
        declared = yaml_subset.load(text)
    except yaml_subset.YamlSubsetError as exc:
        raise DependencyError(f"{DEPENDENCIES_FILE}: {exc}") from exc
    skills = _skill_names(root)
    for skill, names in declared.items():
        if skill not in skills:
            raise DependencyError(
                f"{DEPENDENCIES_FILE}: {skill} declares dependencies but has no SKILL.md")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise DependencyError(
                f"{DEPENDENCIES_FILE}: {skill} must declare a list of skill names")
        for name in names:
            if name not in skills:
                raise DependencyError(
                    f"{DEPENDENCIES_FILE}: {skill} declares {name}, which has no SKILL.md")
    return declared


def _skill_dir_files(root, skill):
    """Root-relative POSIX paths of the surface files under `skills/<skill>/`."""
    base = os.path.join(root, "skills", skill)
    files = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_NAMES]
        for name in filenames:
            if name.startswith("test_") and name.endswith(".py"):
                continue
            if name.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            files.append(rel.replace(os.sep, "/"))
    return files


# Delegation prompts and procedural text name a contract as a bare path rather
# than a markdown link. Reading links alone would drop those real dependencies
# from the surface and report a false negative.
_BARE_PATH_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:md|py|sh)")

_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)")


def _python_import_edges(root, skill):
    """Edges from the skill's own .py to modules under `skills/shared/scripts/`.

    One hop only: a skill's script to a shared module. Imports between shared
    modules are not followed, matching the one-hop rule for markdown links. Only
    module names that exist under `skills/shared/scripts/` are accepted as edges,
    so a same-named module elsewhere cannot produce a false positive — the target
    of these imports is reached through a path inserted at run time, which is why
    the name alone cannot settle it.
    """
    shared_scripts = os.path.join(root, "skills", "shared", "scripts")
    if not os.path.isdir(shared_scripts):
        return set()
    shared_modules = {
        os.path.splitext(f)[0]
        for f in os.listdir(shared_scripts)
        if f.endswith(".py") and not f.startswith("test_")
    }
    skill_dir = os.path.join(root, "skills", skill)
    found = set()
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_NAMES]
        for name in filenames:
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    for line in f:
                        m = _IMPORT_RE.match(line)
                        if m and m.group(1) in shared_modules:
                            found.add(f"skills/shared/scripts/{m.group(1)}.py")
            except OSError:
                continue
    return found


def _bare_path_refs(root, rel):
    """Existing .md/.py/.sh files named as bare paths in `rel`, root-relative.

    Resolution is attempted both from the repository root and from the file's own
    directory: procedural text is written the first way, link-shaped mentions the
    second. Targets that do not exist are ignored, and test_*.py never enters a
    surface.

    Only paths under `skills/` are accepted as dependencies. Procedural text also
    names artifacts that are rewritten at run time and evaluation assets that
    belong to the operator; either on the surface would leave the skill
    permanently stale.
    """
    abs_root = os.path.abspath(root)
    path = os.path.join(abs_root, rel)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return set()
    base = os.path.dirname(path)
    found = set()
    for token in _BARE_PATH_RE.findall(text):
        if "{" in token or "*" in token:
            continue
        basename = os.path.basename(token)
        if basename.startswith("test_") and basename.endswith(".py"):
            continue
        for candidate in (os.path.join(abs_root, token), os.path.join(base, token)):
            resolved = os.path.normpath(candidate)
            if not os.path.isfile(resolved):
                continue
            if os.path.commonpath([abs_root, resolved]) != abs_root:
                continue
            found_rel = os.path.relpath(resolved, abs_root).replace(os.sep, "/")
            if found_rel.startswith("skills/"):
                found.add(found_rel)
    return found


def _own_surface(root, skill):
    """What one skill reaches by itself, as a set. Empty when it has no SKILL.md.

    The starts are every .md and .py inside the skill directory. From .md the
    traversal takes markdown links and bare paths one hop; from .py it takes
    imports of shared modules one hop. Files outside the skill directory join the
    surface, but nothing is traversed out of them.
    """
    skill_md = os.path.join(root, "skills", skill, "SKILL.md")
    if not os.path.isfile(skill_md):
        return set()
    own = _skill_dir_files(root, skill)
    own_md = [rel for rel in own if rel.endswith(".md")]
    surface = set(own)
    surface.update(md_links.closure(root, own_md, max_depth=1))
    for rel in own_md:
        surface.update(_bare_path_refs(root, rel))
    surface.update(_python_import_edges(root, skill))
    return surface


def behavior_surface(root, skill, declared=None):
    """One skill's behaviour surface, sorted. Empty when it has no SKILL.md.

    `declared` is the dependency declaration; it is read from the evaluation
    side when not supplied. A declared skill's own surface joins this one — its
    own, not its behaviour surface, so what it declares in turn is not followed.
    """
    surface = _own_surface(root, skill)
    if not surface:
        return []
    if declared is None:
        declared = load_declared_dependencies(root)
    for name in declared.get(skill, []):
        surface.update(_own_surface(root, name))
    return sorted(surface)


def build_graph(root):
    """{skill name: behaviour surface} for every skill except `shared`."""
    declared = load_declared_dependencies(root)
    return {name: behavior_surface(root, name, declared)
            for name in sorted(_skill_names(root))}


def normalize_path(path, root=None):
    """Normalize a path to repository-relative POSIX form, or None if unresolvable."""
    p = os.path.normpath(path)
    if root and os.path.isabs(p):
        abs_root = os.path.abspath(root)
        if os.path.commonpath([abs_root, p]) != abs_root:
            return None
        p = os.path.relpath(p, abs_root)
    else:
        p = os.path.relpath(p) if os.path.isabs(p) else p
        p = os.path.normpath(p)
    result = p.replace(os.sep, "/")
    if result.startswith(".." + "/"):
        return None
    return result


def impacted_skills(graph, changed_paths, root=None):
    """Skills whose surface intersects the changed files, sorted, plus unresolvable inputs."""
    changed = set()
    unresolved = []
    for p in changed_paths:
        norm = normalize_path(p, root)
        if norm is None:
            unresolved.append(p)
        else:
            changed.add(norm)
    return sorted(
        skill for skill, surface in graph.items() if changed.intersection(surface)
    ), unresolved


def main(argv):
    args = list(argv)
    changed = None
    if "--impact" in args:
        idx = args.index("--impact")
        rest = args[idx + 1:]
        args = args[:idx]
        # A trailing existing directory is the root; anything else is a changed file.
        if rest and os.path.isdir(rest[-1]) and not rest[-1].endswith(".md"):
            args.append(rest[-1])
            rest = rest[:-1]
        changed = rest
    root = args[0] if args else os.getcwd()
    try:
        graph = build_graph(root)
    except DependencyError as exc:
        print(exc, file=sys.stderr)
        return 1
    if changed is None:
        print(json.dumps(graph, ensure_ascii=False, indent=2))
    else:
        skills, unresolved = impacted_skills(graph, changed, root)
        for skill in skills:
            print(skill)
        for p in unresolved:
            print(f"warning: unresolvable path: {p}", file=sys.stderr)
        if unresolved:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
