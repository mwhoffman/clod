"""Model of the projects and conversations Claude Code keeps on disk."""

import contextlib
import dataclasses
import datetime
import json
import os
import pathlib
import re
import secrets
import shutil
import time
from collections.abc import Iterator
from typing import Any


# Base directory for claude settings.
CLAUDE_DIR = pathlib.Path.home() / ".claude"

# Directory holding a conversations directory for each project.
PROJECTS_DIR = CLAUDE_DIR / "projects"

# Directories with an entry per conversation, named by its session id.
SESSION_DIRS = (CLAUDE_DIR / "session-env", CLAUDE_DIR / "file-history")

# Directory with a file per running session, named by pid.
LIVE_DIR = CLAUDE_DIR / "sessions"

# Directory in which Claude Code keeps per-project caches, named like the
# conversations directories.
CACHE_DIR = pathlib.Path.home() / ".cache" / "claude-cli-nodejs"

# Directory with a directory per conversation that ran in the background, named
# by the start of its session id.
JOBS_DIR = CLAUDE_DIR / "jobs"

# File in which the background daemon records the jobs it is managing.
ROSTER_FILE = CLAUDE_DIR / "daemon" / "roster.json"

# File in which Claude Code records every prompt typed, one per line.
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"

# File in which Claude Code records the projects it has been run in.
CONFIG_FILE = pathlib.Path.home() / ".claude.json"

# Seconds to wait for a lock held by a running Claude Code before giving up.
LOCK_TIMEOUT = 5.0


@dataclasses.dataclass(frozen=True)
class Conversation:
  """A conversation, stored as a JSONL file with one record per line.

  Attributes:
    path: Location of the conversation file.
  """

  path: pathlib.Path

  @property
  def id(self) -> str:
    """Session id of the conversation, which is the stem of its filename."""
    return self.path.stem

  def records(self) -> Iterator[dict[str, Any]]:
    """Read the records of the conversation, skipping lines that are invalid.

    Yields:
      Each record, in order.
    """
    with self.path.open() as f:
      for line in f:
        try:
          record = json.loads(line)
        except json.JSONDecodeError:
          continue
        if isinstance(record, dict):
          yield record

  def modified(self) -> datetime.datetime:
    """Find when the conversation was last written to.

    Returns:
      The modification time of the conversation file, in local time.
    """
    return datetime.datetime.fromtimestamp(
      self.path.stat().st_mtime
    ).astimezone()

  def is_empty(self) -> bool:
    """Check whether the conversation never got started.

    Returns:
      Whether the conversation has neither a prompt typed by the user nor a
      reply from the assistant.
    """
    for record in self.records():
      kind = record.get("type")
      if kind == "user" and prompt_text(record):
        return False
      if kind == "assistant" and not record.get("isSidechain"):
        return False
    return True

  def cwds(self) -> Iterator[str]:
    """Find the working directories the conversation ran in.

    Yields:
      Each distinct working directory, in the order they first appear.
    """
    seen: set[str] = set()
    for record in self.records():
      cwd = record.get("cwd")
      if isinstance(cwd, str) and cwd not in seen:
        seen.add(cwd)
        yield cwd


@dataclasses.dataclass(frozen=True)
class Session:
  """A conversation that Claude Code is currently running.

  Attributes:
    id: Session id of the conversation.
    pid: Id of the process running it.
    cwd: Working directory it was started in.
  """

  id: str
  pid: int
  cwd: pathlib.Path


@dataclasses.dataclass(frozen=True)
class Project:
  """A project known to Claude Code.

  Attributes:
    path: Working directory of the project, which identifies it.
  """

  path: pathlib.Path

  def conversations_dir(self) -> pathlib.Path:
    """Find the directory holding the conversations of the project.

    Returns:
      The directory under ~/.claude/projects named after the working
      directory, with every character other than a letter or digit replaced by
      "-". It may not exist.
    """
    return PROJECTS_DIR / re.sub(r"[^a-zA-Z0-9]", "-", str(self.path.resolve()))

  def conversations(self) -> list[Conversation]:
    """List the conversations of the project.

    Returns:
      Every conversation, including empty ones, most recently modified first.
    """
    return sorted(
      (Conversation(p) for p in self.conversations_dir().glob("*.jsonl")),
      key=lambda c: c.path.stat().st_mtime,
      reverse=True,
    )

  def modified(self) -> datetime.datetime | None:
    """Find when the project was last used.

    Returns:
      The modification time of the newest conversation that is not empty, or
      None if there is no such conversation.
    """
    for conversation in self.conversations():
      if not conversation.is_empty():
        return conversation.modified()
    return None

  def exists(self) -> bool:
    """Check whether the working directory of the project still exists."""
    return self.path.is_dir()


def prompt_text(record: dict[str, Any]) -> str | None:
  """Extract the text the user typed from a user record.

  Args:
    record: A conversation record of type "user".

  Returns:
    The typed prompt, or None if the record is not a prompt typed by the user
    (e.g. a tool result or a message injected by the harness).
  """
  if (
    record.get("isMeta")
    or record.get("isSidechain")
    or "toolUseResult" in record
  ):
    return None
  content = record.get("message", {}).get("content")
  if isinstance(content, list):
    content = "\n".join(
      b.get("text", "")
      for b in content
      if isinstance(b, dict) and b.get("type") == "text"
    )
  if not isinstance(content, str):
    return None
  # Drop harness-injected blocks so only the typed prompt remains.
  content = re.sub(
    r"<(system-reminder|local-command-\w+)>.*?</\1>",
    "",
    content,
    flags=re.DOTALL,
  )
  return content.strip() or None


def registered_projects() -> list[Project]:
  """Find the projects recorded in the Claude Code config file.

  Returns:
    The projects, which is empty if the config file cannot be read.
  """
  registered = read_json(CONFIG_FILE).get("projects")
  if not isinstance(registered, dict):
    return []
  return [Project(pathlib.Path(path)) for path in registered]


def match(directory: pathlib.Path) -> Project | None:
  """Recover the project a conversations directory belongs to.

  The name of a conversations directory is a lossy encoding of the working
  directory, so the working directory is read from the conversations instead.
  A conversation can move into other directories, so only a working directory
  which maps back to the conversations directory is used.

  Args:
    directory: A directory under ~/.claude/projects.

  Returns:
    The project, or None if no conversation names its working directory.
  """
  for path in sorted(directory.glob("*.jsonl")):
    for cwd in Conversation(path).cwds():
      project = Project(pathlib.Path(cwd))
      if project.conversations_dir() == directory:
        return project
  return None


def projects() -> list[Project]:
  """Find the projects known to Claude Code.

  Returns:
    The projects recorded in the config file or found under ~/.claude/projects,
    ordered by working directory.
  """
  found = set(registered_projects())
  claimed = {p.conversations_dir() for p in found}
  if PROJECTS_DIR.is_dir():
    for directory in PROJECTS_DIR.iterdir():
      if directory.is_dir() and directory not in claimed:
        project = match(directory)
        if project:
          found.add(project)
  return sorted(found, key=lambda p: p.path)


def unmatched_dirs(projects: list[Project]) -> list[pathlib.Path]:
  """Find the conversations directories that belong to no project.

  Args:
    projects: The projects known to Claude Code.

  Returns:
    The directories under ~/.claude/projects that are not the conversations
    directory of any of the projects, in name order.
  """
  if not PROJECTS_DIR.is_dir():
    return []
  claimed = {p.conversations_dir() for p in projects}
  return sorted(
    d for d in PROJECTS_DIR.iterdir() if d.is_dir() and d not in claimed
  )


def read_json(path: pathlib.Path) -> dict[str, Any]:
  """Read a file holding a JSON object.

  Args:
    path: Location of the file.

  Returns:
    The object, which is empty if the file cannot be read or holds anything
    else.
  """
  try:
    value = json.loads(path.read_text())
  except (OSError, json.JSONDecodeError):
    return {}
  return value if isinstance(value, dict) else {}


def roster() -> dict[str, Any]:
  """Find the jobs the background daemon is managing.

  Returns:
    A mapping from the name of each job, which is also the name of its
    directory under ~/.claude/jobs, to what the daemon has recorded about it.
  """
  workers = read_json(ROSTER_FILE).get("workers")
  return workers if isinstance(workers, dict) else {}


def is_running(pid: int) -> bool:
  """Check whether a process exists.

  Args:
    pid: Id of the process.

  Returns:
    Whether there is a process with the id, which may belong to another user.
  """
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  return True


def live_sessions() -> list[Session]:
  """Find the conversations that Claude Code is currently running.

  Returns:
    The sessions recorded under ~/.claude/sessions or by the background daemon
    whose process is still running.
  """
  entries = [read_json(path) for path in LIVE_DIR.glob("*.json")]
  entries += [e for e in roster().values() if isinstance(e, dict)]
  sessions: list[Session] = []
  for entry in entries:
    session, pid, cwd = (entry.get(k) for k in ("sessionId", "pid", "cwd"))
    if (
      isinstance(session, str)
      and isinstance(pid, int)
      and isinstance(cwd, str)
      and is_running(pid)
    ):
      sessions.append(Session(session, pid, pathlib.Path(cwd)))
  return sessions


def delete(path: pathlib.Path) -> None:
  """Delete a file or a directory and everything in it.

  Args:
    path: Path to delete. A symbolic link is removed without touching what it
      points to.
  """
  if path.is_dir() and not path.is_symlink():
    shutil.rmtree(path)
  else:
    path.unlink()


@contextlib.contextmanager
def lock(path: pathlib.Path) -> Iterator[None]:
  """Hold the lock Claude Code takes before it writes to a file.

  The lock is a directory next to the file, with ".lock" added to its name,
  which exists for as long as the lock is held.

  Args:
    path: Location of the file to lock.

  Raises:
    TimeoutError: If the lock is still held by something else after
      LOCK_TIMEOUT seconds. A lock is never taken over, even if whatever held
      it has gone away.
  """
  directory = path.with_name(f"{path.name}.lock")
  deadline = time.monotonic() + LOCK_TIMEOUT
  while True:
    try:
      directory.mkdir()
      break
    except FileExistsError:
      if time.monotonic() > deadline:
        raise TimeoutError(f"{directory} is held") from None
      time.sleep(0.05)
  try:
    yield
  finally:
    directory.rmdir()


def replace(path: pathlib.Path, text: str) -> None:
  """Replace the contents of a file in a single step.

  The text is written to a temporary file next to the file, which is then
  renamed over it, so that the file is never seen half written.

  Args:
    path: Location of the file, which must exist.
    text: New contents of the file.
  """
  temporary = path.with_name(
    f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(6)}"
  )
  mode = path.stat().st_mode & 0o777
  with os.fdopen(
    os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "w"
  ) as f:
    f.write(text)
  temporary.replace(path)
