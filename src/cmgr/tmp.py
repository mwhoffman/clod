"""Run Claude Code in a new temporary project."""

import json
import os
import pathlib
import secrets
import sys
from typing import Any

from cmgr import common


def trust(directory: pathlib.Path) -> None:
  """Have Claude Code trust a directory without asking.

  Claude Code trusts a directory outside a git repository if the config file
  says it has accepted the trust dialog for the directory or one above it.
  Nothing is changed if the config file cannot be read or its lock is held, in
  which case Claude Code asks as usual.

  Args:
    directory: Directory to trust, along with everything in it.
  """

  def accept(config: dict[str, Any]) -> bool:
    """Record the trust in a config, returning whether that changed it."""
    projects = config.get("projects")
    if not isinstance(projects, dict):
      return False
    entry = projects.setdefault(str(directory), {})
    if not isinstance(entry, dict) or entry.get("hasTrustDialogAccepted"):
      return False
    entry["hasTrustDialogAccepted"] = True
    return True

  if not accept(common.read_json(common.CONFIG_FILE)):
    return
  try:
    with common.lock(common.CONFIG_FILE):
      # Read the file again now that nothing else can be writing to it.
      config = common.read_json(common.CONFIG_FILE)
      if accept(config):
        common.replace(
          common.CONFIG_FILE,
          json.dumps(config, indent=2, ensure_ascii=False),
        )
  except TimeoutError:
    pass


def run() -> None:
  """Create a temporary project and replace this process with Claude Code.

  The project is an empty directory under TMP_DIR, which the clean command
  purges once Claude Code is no longer running in it. TMP_DIR is trusted, so
  that Claude Code does not ask whether to trust each new project.
  """
  common.TMP_DIR.mkdir(parents=True, exist_ok=True)
  parent = common.TMP_DIR.resolve()
  trust(parent)
  while True:
    directory = parent / f"tmp-{secrets.token_hex(2)}"
    # A name is not used again while Claude Code still has conversations for
    # it, which would otherwise become those of the new project.
    if common.Project(directory).conversations_dir().exists():
      continue
    try:
      directory.mkdir()
      break
    except FileExistsError:
      continue
  os.chdir(directory)
  try:
    os.execvp("claude", ["claude"])
  except FileNotFoundError:
    directory.rmdir()
    sys.exit("claude was not found on the path")
