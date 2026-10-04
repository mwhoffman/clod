"""Delete Claude Code state that no longer refers to anything."""

import pathlib
import sys

import typer

from cmgr import common
from cmgr import console as console_lib
from cmgr import purge as purge_lib


# Paths grouped by a description of what they are.
Groups = dict[str, list[pathlib.Path]]


def children(directory: pathlib.Path) -> list[pathlib.Path]:
  """List the contents of a directory.

  Args:
    directory: Directory to list, which may not exist.

  Returns:
    The entries of the directory in name order, which is empty if it does not
    exist.
  """
  return sorted(directory.iterdir()) if directory.is_dir() else []


def temporary() -> dict[common.Project, purge_lib.Plan]:
  """Find the temporary projects that Claude Code is not running in.

  Returns:
    A mapping from each such project to what purging it would do, in order of
    working directory.
  """
  cwds = [s.cwd for s in common.live_sessions()]
  plans: dict[common.Project, purge_lib.Plan] = {}
  for directory in sorted(common.TMP_DIR.glob("tmp-*")):
    if directory.is_symlink() or not directory.is_dir():
      continue
    path = directory.resolve()
    if any(cwd == path or path in cwd.parents for cwd in cwds):
      continue
    project = common.Project(path)
    todo = purge_lib.plan(project)
    # A project sharing its conversations directory is left for the purge
    # command, which warns about it.
    if not todo.shared:
      plans[project] = todo
  return plans


def find(purged: list[pathlib.Path]) -> Groups:
  """Find state that no longer refers to anything.

  Args:
    purged: Paths that are being deleted anyway, which are left out along with
      everything in them.

  Returns:
    The paths that can be deleted, grouped by kind and omitting kinds for which
    there are none.
  """
  projects = common.projects()
  names = {p.conversations_dir().name for p in projects}
  live = {s.id for s in common.live_sessions()}
  rostered = set(common.roster())
  conversations = [
    common.Conversation(p)
    for p in sorted(common.PROJECTS_DIR.glob("*/*.jsonl"))
  ]
  empty = [c for c in conversations if c.id not in live and c.is_empty()]
  # Session ids whose state is still in use, which are those of conversations
  # that are running or are being kept.
  sessions = live | {c.id for c in conversations if c not in empty}

  doomed = {
    "Conversations with no prompts or replies": [c.path for c in empty],
    "Empty conversations directories with no project": [
      d for d in common.unmatched_dirs(projects) if not children(d)
    ],
    "Caches for directories that are not projects": [
      d for d in children(common.CACHE_DIR) if d.name not in names
    ],
    "State for conversations that no longer exist": [
      d
      for directory in common.SESSION_DIRS
      for d in children(directory)
      if d.name not in sessions
    ],
    "Jobs for conversations that no longer exist": [
      d
      for d in children(common.JOBS_DIR)
      if d.is_dir()
      and d.name not in rostered
      and not any(s.startswith(d.name) for s in sessions)
    ],
  }
  kept = {
    kind: [
      p for p in paths if not any(t == p or t in p.parents for t in purged)
    ]
    for kind, paths in doomed.items()
  }
  return {kind: paths for kind, paths in kept.items() if paths}


def run(yes: bool = False, dry_run: bool = False) -> None:
  """Delete state that no longer refers to anything.

  Temporary projects that Claude Code is not running in are also purged, and
  their working directories deleted.

  Args:
    yes: Whether to delete without asking for confirmation.
    dry_run: Whether to only print what would be deleted.
  """
  console = console_lib.make_console()
  plans = temporary()
  doomed = find([t for todo in plans.values() for t in todo.delete])
  if not (doomed or plans):
    console.print("Nothing to clean.")
    return
  for kind, group in doomed.items():
    console.print(f"{kind}:", style="header")
    for path in group:
      console.print(path)
    console.print()
  if plans:
    console.print("Temporary projects that are not running:", style="header")
    for project in plans:
      console.print(project.path)
    console.print()

  paths = [path for group in doomed.values() for path in group]
  count = len(paths) + len(plans)
  if dry_run:
    return
  if not yes:
    typer.confirm(f"Delete these {count} items?", abort=True)
  for path in paths:
    common.delete(path)
  try:
    for project, todo in plans.items():
      purge_lib.apply(project, todo)
      common.delete(project.path)
  except TimeoutError as error:
    sys.exit(f"Stopped before purging every temporary project: {error}")
  console.print(f"Deleted {count} items.")
