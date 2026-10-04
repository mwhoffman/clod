"""Run Claude Code in a project, continuing its last conversation."""

import os
import pathlib
import sys

from clod import common


def taken_by(project: common.Project) -> str | None:
  """Find what else is using the conversations directory of a project.

  The name of a conversations directory is a lossy encoding of the working
  directory, so different working directories can map to the same one.

  Args:
    project: The project.

  Returns:
    The working directory of another project in the config file which maps to
    the same conversations directory, or "a missing project" if the directory
    exists without the config file having either that or the project itself.
    None if the project has its conversations directory to itself.
  """
  directory = project.conversations_dir()
  registered = common.registered_projects()
  for other in registered:
    if other.path != project.path and other.conversations_dir() == directory:
      return str(other.path)
  if project not in registered and directory.exists():
    return "a missing project"
  return None


def run(directory: pathlib.Path, *, new: bool) -> None:
  """Replace this process with Claude Code running in a project.

  The most recent conversation of the project is continued if it has one,
  unless Claude Code is already running in the project, since that may be the
  conversation it is running.

  Args:
    directory: Working directory of the project.
    new: Whether to start a new conversation even if one could be continued.
  """
  if not directory.is_dir():
    sys.exit(f"{directory} is not a directory")
  project = common.Project(directory.resolve())
  taken = taken_by(project)
  if taken:
    sys.exit(
      f"{project.path} is already taken by {taken} (due to Claude Code's lossy"
      " name mangling)"
    )
  args = ["claude"]
  # Claude Code exits if it is asked to continue with nothing to continue.
  if not new and project.modified() is not None:
    # The conversation to continue may be the one that is running, which two
    # instances of Claude Code would then both be writing to.
    pids = [s.pid for s in common.live_sessions() if s.cwd == project.path]
    if pids:
      sys.exit(
        f"Claude Code is already running in {project.path} (pid"
        f" {', '.join(map(str, sorted(pids)))}); use --new to start a new"
        " conversation alongside it"
      )
    args.append("-c")
  os.chdir(project.path)
  try:
    os.execvp("claude", args)
  except FileNotFoundError:
    sys.exit("claude was not found on the path")
