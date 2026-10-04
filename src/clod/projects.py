"""List the projects known to Claude Code, in order of working directory."""

import sys

import humanize
import rich.text

from clod import common
from clod import console as console_lib


def run() -> None:
  """Print a line for each project."""
  # Temporary projects, and the directory holding them, are left out.
  tmp = common.TMP_DIR.resolve()
  projects = [
    p for p in common.projects() if p.path != tmp and tmp not in p.path.parents
  ]
  if not projects:
    sys.exit("No Claude Code projects found.")

  # Ordered without regard to case, as a directory listing would be.
  projects.sort(key=lambda p: (str(p.path).casefold(), p.path))

  console = console_lib.make_console()
  for project in projects:
    when = project.modified()
    age = humanize.naturaltime(when) if when else "never"
    if not project.exists():
      age += ", missing"
    console.print(
      rich.text.Text.assemble(f"{project.path} ", (f"({age})", "dim"))
    )
