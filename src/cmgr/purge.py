"""Delete everything Claude Code has stored about a project."""

import dataclasses
import json
import pathlib
import sys
from typing import Any

import rich.text
import typer

from cmgr import common
from cmgr import console as console_lib


@dataclasses.dataclass
class Plan:
  """What purging a project would do.

  Attributes:
    delete: Files and directories to delete.
    entry: Whether the config file has an entry for the project.
    repos: Number of GitHub repositories the config file maps to the project.
    prompts: Number of prompts typed in the project in the prompt history.
    shared: Other working directories whose conversations are stored with
      those of the project, with the number of conversations of each.
  """

  delete: list[pathlib.Path]
  entry: bool
  repos: int
  prompts: int
  shared: dict[pathlib.Path, int]


def without_project(config: dict[str, Any], path: str) -> tuple[bool, int]:
  """Remove what a config says about a project.

  Args:
    config: Contents of the config file, which are changed in place.
    path: Working directory of the project.

  Returns:
    Whether an entry for the project was removed, and the number of GitHub
    repositories that were mapped to it.
  """
  projects = config.get("projects")
  entry = isinstance(projects, dict) and projects.pop(path, None) is not None
  repos = 0
  mapping = config.get("githubRepoPaths")
  if isinstance(mapping, dict):
    for repo, paths in list(mapping.items()):
      if isinstance(paths, list) and path in paths:
        repos += 1
        paths.remove(path)
        if not paths:
          del mapping[repo]
  return entry, repos


def other_lines(path: str) -> tuple[list[str], int]:
  """Split the prompt history into the prompts of a project and the rest.

  Args:
    path: Working directory of the project.

  Returns:
    The lines of the prompt history that are not prompts typed in the project,
    and the number of lines that are.
  """
  kept: list[str] = []
  try:
    lines = common.HISTORY_FILE.read_text().splitlines(keepends=True)
  except OSError:
    return kept, 0
  for line in lines:
    try:
      record = json.loads(line)
    except json.JSONDecodeError:
      record = None
    if not isinstance(record, dict) or record.get("project") != path:
      kept.append(line)
  return kept, len(lines) - len(kept)


def sharing(project: common.Project) -> dict[pathlib.Path, int]:
  """Find the working directories a project shares its conversations with.

  The name of a conversations directory is a lossy encoding of the working
  directory, so different working directories can map to the same one.

  Args:
    project: The project.

  Returns:
    A mapping from each other working directory which uses the conversations
    directory of the project to the number of conversations that ran in it.
  """
  directory = project.conversations_dir()
  shared = {
    p.path: 0
    for p in common.registered_projects()
    if p.path != project.path and p.conversations_dir() == directory
  }
  for conversation in project.conversations():
    for cwd in conversation.cwds():
      other = common.Project(pathlib.Path(cwd))
      if other.path != project.path and other.conversations_dir() == directory:
        shared[other.path] = shared.get(other.path, 0) + 1
  return shared


def plan(project: common.Project) -> Plan:
  """Work out what purging a project would do.

  Args:
    project: The project.

  Returns:
    What would be deleted and changed, without doing any of it.
  """
  directory = project.conversations_dir()
  rostered = set(common.roster())
  candidates = [directory, common.CACHE_DIR / directory.name]
  for conversation in project.conversations():
    candidates += [d / conversation.id for d in common.SESSION_DIRS]
    # A job the background daemon still knows about is left for it to remove.
    job = conversation.id[:8]
    if job not in rostered:
      candidates.append(common.JOBS_DIR / job)

  path = str(project.path)
  entry, repos = without_project(common.read_json(common.CONFIG_FILE), path)
  _, prompts = other_lines(path)
  return Plan(
    delete=[c for c in candidates if c.exists() or c.is_symlink()],
    entry=entry,
    repos=repos,
    prompts=prompts,
    shared=sharing(project),
  )


def apply(project: common.Project, todo: Plan) -> None:
  """Purge a project.

  The config file and prompt history are changed first, while holding the
  locks Claude Code takes to write to them, so that nothing has been deleted
  if a lock cannot be taken.

  Args:
    project: The project.
    todo: What purging the project should do.

  Raises:
    TimeoutError: If a lock is held by something else.
  """
  path = str(project.path)
  with common.lock(common.CONFIG_FILE), common.lock(common.HISTORY_FILE):
    if todo.entry or todo.repos:
      # Read the file again now that nothing else can be writing to it.
      config = common.read_json(common.CONFIG_FILE)
      if any(without_project(config, path)):
        common.replace(
          common.CONFIG_FILE,
          json.dumps(config, indent=2, ensure_ascii=False),
        )
    if todo.prompts:
      kept, removed = other_lines(path)
      if removed:
        common.replace(common.HISTORY_FILE, "".join(kept))
  for target in todo.delete:
    common.delete(target)


def run(path: pathlib.Path, yes: bool = False, dry_run: bool = False) -> None:
  """Delete everything Claude Code has stored about a project.

  Args:
    path: Working directory of the project.
    yes: Whether to purge without asking for confirmation.
    dry_run: Whether to only print what would be purged.
  """
  project = common.Project(path.resolve())
  running = [s for s in common.live_sessions() if s.cwd == project.path]
  if running:
    pids = ", ".join(str(s.pid) for s in running)
    sys.exit(f"Claude Code is running in {project.path} (pid {pids})")

  todo = plan(project)
  if not (todo.delete or todo.entry or todo.repos or todo.prompts):
    sys.exit(f"No Claude Code state found for {project.path}")

  console = console_lib.make_console()
  if todo.shared:
    console.print(
      "Warning: these projects share a conversations directory with this one,"
      " so their conversations will also be deleted:",
      style="warning",
    )
    for other, count in sorted(todo.shared.items()):
      console.print(
        rich.text.Text.assemble(
          f"{other} ", (f"({count} conversations)", "dim")
        )
      )
    console.print()
  if todo.delete:
    console.print("To delete:", style="header")
    for target in todo.delete:
      console.print(target)
    console.print()
  changes = {
    common.CONFIG_FILE: ", ".join(
      detail
      for detail in (
        "project entry" if todo.entry else "",
        f"{todo.repos} GitHub repo paths" if todo.repos else "",
      )
      if detail
    ),
    common.HISTORY_FILE: f"{todo.prompts} prompts" if todo.prompts else "",
  }
  if any(changes.values()):
    console.print("To change:", style="header")
    for target, detail in changes.items():
      if detail:
        console.print(
          rich.text.Text.assemble(f"{target} ", (f"(remove {detail})", "dim"))
        )
    console.print()

  if dry_run:
    return
  if todo.shared and yes:
    sys.exit("Not purging a shared conversations directory without asking")
  if not yes:
    typer.confirm(f"Purge {project.path}?", abort=True)
  try:
    apply(project, todo)
  except TimeoutError as error:
    sys.exit(f"Nothing was purged: {error}")
  console.print(f"Purged {project.path}.")
