#!/usr/bin/env python3
"""Extraction of relative markdown links and the reachable closure over them.

Pure functions. Anchors are stripped, and targets that name nothing checkable —
URLs, rooted paths, `{var}` / `*` placeholders, and example filenames that open
with a timestamp — are left out.
"""
import collections
import os
import re

_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_TIMESTAMP_EXAMPLE = re.compile(r"^\d{8,}")
_UNCHECKABLE_PREFIXES = ("http://", "https://", "mailto:", "#", "/")


def extract_md_links(text):
    """Return the `.md` link targets in a markdown text, anchors stripped."""
    links = []
    for target in _LINK_RE.findall(text):
        target = target.split("#", 1)[0]
        if target.endswith(".md"):
            links.append(target)
    return links


def is_checkable_link(link):
    """True when the link is a relative `.md` target whose existence is worth checking."""
    if not link.endswith(".md"):
        return False
    if link.startswith(_UNCHECKABLE_PREFIXES):
        return False
    if "{" in link or "*" in link:
        return False
    if _TIMESTAMP_EXAMPLE.match(os.path.basename(link)):
        return False
    return True


def closure(root, start_rel, max_depth=None):
    """Files reachable from `start_rel` through relative `.md` links.

    `start_rel` is one path or an iterable of paths; several starts all sit at
    depth 0. `max_depth` bounds the hops taken from a start — None is unbounded,
    1 stops at directly linked files. Links leaving `root` and targets that do
    not exist are not followed. The result is a sorted list of root-relative
    POSIX paths, empty when no start exists.

    The depth bound exists because an unbounded closure treats "linked at all"
    as "affects behaviour": one related-reading link between shared contracts
    puts skills whose execution paths never meet onto the same surface. Depth is
    counted breadth-first, so first arrival is the shortest hop.
    """
    root = os.path.abspath(root)
    starts = [start_rel] if isinstance(start_rel, str) else list(start_rel)
    queue = collections.deque()
    seen = set()
    for rel in starts:
        path = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(path) and path not in seen:
            seen.add(path)
            queue.append((path, 0))
    while queue:
        path, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        base = os.path.dirname(path)
        for link in extract_md_links(text):
            if not is_checkable_link(link):
                continue
            target = os.path.normpath(os.path.join(base, link))
            if os.path.commonpath([root, target]) != root:
                continue
            if os.path.isfile(target) and target not in seen:
                seen.add(target)
                queue.append((target, depth + 1))
    return sorted(os.path.relpath(p, root).replace(os.sep, "/") for p in seen)
