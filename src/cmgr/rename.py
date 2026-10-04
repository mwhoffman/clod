"""Rename a conversation."""

import json
import os
import readline
import sys

from cmgr import common
from cmgr import console as console_lib
from cmgr import conversations as conversations_lib


# Name of the file, in the directory next to a conversation, in which Claude
# Code keeps the name the user gave it.
TITLE_FILE = "custom-title.json"


def ask(current: str) -> str:
  """Ask for a name on the terminal.

  Args:
    current: Name to start with, which can be edited.

  Returns:
    The name typed.
  """
  readline.set_startup_hook(lambda: readline.insert_text(current))
  try:
    return input("name: ")
  except (EOFError, KeyboardInterrupt):
    sys.exit("\nNot renamed.")
  finally:
    readline.set_startup_hook()


def compact(value: dict[str, str]) -> str:
  """Encode a JSON object the way Claude Code does, without any spacing."""
  return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def apply(conversation: common.Conversation, name: str) -> None:
  """Give a conversation a name, as renaming it in Claude Code would.

  The name is added to the end of the conversation, without changing when it
  was last modified, and written to the file next to it that holds its name.

  Args:
    conversation: The conversation, which must not be running.
    name: The new name.
  """
  path = conversation.path
  records = [
    {"type": "custom-title", "customTitle": name, "sessionId": conversation.id},
    {"type": "agent-name", "agentName": name, "sessionId": conversation.id},
  ]
  text = path.read_text()
  lines = "".join(f"{compact(record)}\n" for record in records)
  stat = path.stat()
  with path.open("a") as f:
    f.write(lines if not text or text.endswith("\n") else f"\n{lines}")
  os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

  directory = path.with_suffix("")
  directory.mkdir(mode=0o700, exist_ok=True)
  target = directory / TITLE_FILE
  title = compact({"customTitle": name})
  if target.exists():
    common.replace(target, title)
  else:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(target, flags, 0o600), "w") as f:
      f.write(title)


def run(prefix: str, name: str | None = None) -> None:
  """Rename a conversation.

  Args:
    prefix: Session id of the conversation, or the start of it.
    name: The new name. If not given it is asked for on the terminal, starting
      from the current name.
  """
  (conversation,) = common.resolve([prefix])
  running = [s for s in common.live_sessions() if s.id == conversation.id]
  if running:
    pid = running[0].pid
    sys.exit(
      f"Claude Code is running conversation {conversation.id} (pid {pid})"
    )

  summary = conversations_lib.summarize(conversation)
  current = summary.custom_title or summary.title or ""
  if name is None:
    if not sys.stdin.isatty():
      sys.exit("No name given, and no terminal to ask for one; use --name")
    name = ask(current)
  # A name is a single line.
  name = " ".join(name.split())
  if not name:
    sys.exit("Not renaming to an empty name.")
  console = console_lib.make_console()
  if name == current:
    console.print("Name unchanged.")
    return
  apply(conversation, name)
  console.print(f"Renamed {conversation.id} to {name!r}.")
