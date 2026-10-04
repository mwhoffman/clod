"""Delete conversations."""

import dataclasses
import pathlib
import sys

import humanize
import rich.text
import typer

from cmgr import common
from cmgr import console as console_lib
from cmgr import conversations as conversations_lib


@dataclasses.dataclass
class Plan:
  """What deleting conversations would do.

  Attributes:
    conversations: The conversations to delete.
    delete: Files and directories to delete.
    prompts: Number of prompts typed in the conversations in the prompt
      history.
  """

  conversations: list[common.Conversation]
  delete: list[pathlib.Path]
  prompts: int


def resolve(prefixes: list[str]) -> list[common.Conversation]:
  """Find the conversations that session ids, or the starts of them, refer to.

  Conversations of every project are searched. The program exits, naming
  every problem, unless each prefix refers to exactly one conversation.

  Args:
    prefixes: Session ids, or the start of each.

  Returns:
    The conversations, in the order given and without repeats.
  """
  known = [
    common.Conversation(p)
    for p in sorted(common.PROJECTS_DIR.glob("*/*.jsonl"))
  ]
  found: list[common.Conversation] = []
  problems: list[str] = []
  for prefix in prefixes:
    matches = [c for c in known if prefix and c.id.startswith(prefix)]
    if not matches:
      problems.append(f"No conversation has an id starting with {prefix!r}")
    elif len(matches) > 1:
      ids = ", ".join(c.id for c in matches)
      problems.append(f"Several conversations match {prefix!r}: {ids}")
    elif matches[0] not in found:
      found.append(matches[0])
  if problems:
    sys.exit("\n".join(problems))
  return found


def other_lines(sessions: set[str]) -> tuple[list[str], int]:
  """Split the prompt history into the prompts of conversations and the rest.

  Args:
    sessions: Session ids of the conversations.

  Returns:
    The lines of the prompt history that are not prompts typed in the
    conversations, and the number of lines that are.
  """
  return common.split_history(
    lambda record: record.get("sessionId") in sessions
  )


def plan(conversations: list[common.Conversation]) -> Plan:
  """Work out what deleting conversations would do.

  Args:
    conversations: The conversations.

  Returns:
    What would be deleted and changed, without doing any of it.
  """
  rostered = set(common.roster())
  candidates: list[pathlib.Path] = []
  for conversation in conversations:
    # Next to a conversation is a directory of the same name for what does
    # not fit in it, such as large tool results.
    candidates += [conversation.path, conversation.path.with_suffix("")]
    candidates += [d / conversation.id for d in common.SESSION_DIRS]
    # A job the background daemon still knows about is left for it to remove.
    job = conversation.id[:8]
    if job not in rostered:
      candidates.append(common.JOBS_DIR / job)
  _, prompts = other_lines({c.id for c in conversations})
  return Plan(
    conversations=conversations,
    delete=[c for c in candidates if c.exists() or c.is_symlink()],
    prompts=prompts,
  )


def apply(todo: Plan) -> None:
  """Delete conversations.

  The prompt history is changed first, while holding the lock Claude Code
  takes to write to it, so that nothing has been deleted if the lock cannot
  be taken.

  Args:
    todo: What deleting the conversations should do.

  Raises:
    TimeoutError: If the lock is held by something else.
  """
  if todo.prompts:
    with common.lock(common.HISTORY_FILE):
      kept, removed = other_lines({c.id for c in todo.conversations})
      if removed:
        common.replace(common.HISTORY_FILE, "".join(kept))
  for target in todo.delete:
    common.delete(target)


def run(prefixes: list[str], yes: bool = False, dry_run: bool = False) -> None:
  """Delete conversations and what Claude Code has stored about them.

  Args:
    prefixes: Session ids of the conversations, or the start of each.
    yes: Whether to delete without asking for confirmation.
    dry_run: Whether to only print what would be deleted.
  """
  conversations = resolve(prefixes)
  sessions = {c.id for c in conversations}
  running = [s for s in common.live_sessions() if s.id in sessions]
  if running:
    sys.exit(
      "\n".join(
        f"Claude Code is running conversation {s.id} (pid {s.pid})"
        for s in running
      )
    )

  todo = plan(conversations)
  console = console_lib.make_console()
  for conversation in conversations:
    summary = conversations_lib.summarize(conversation)
    project = common.match(conversation.path.parent)
    title = summary.custom_title or summary.title or "(untitled)"
    fields = {
      "id": conversation.id,
      "project": str(project.path) if project else "(unknown)",
      "last modified": humanize.naturaltime(summary.modified),
    }
    console.print(title, style="header")
    for key, value in fields.items():
      console.print(rich.text.Text.assemble((f"{key}:", "key"), f" {value}"))
    console.print()
  console.print("To delete:", style="header")
  for target in todo.delete:
    console.print(target)
  console.print()
  if todo.prompts:
    console.print("To change:", style="header")
    console.print(
      rich.text.Text.assemble(
        f"{common.HISTORY_FILE} ",
        (f"(remove {todo.prompts} prompts)", "dim"),
      )
    )
    console.print()

  if dry_run:
    return
  count = len(conversations)
  what = "1 conversation" if count == 1 else f"{count} conversations"
  if not yes:
    typer.confirm(f"Delete {what}?", abort=True)
  try:
    apply(todo)
  except TimeoutError as error:
    sys.exit(f"Nothing was deleted: {error}")
  console.print(f"Deleted {what}.")
