"""Command line interface for clod."""

import pathlib
from typing import Annotated

import typer

from clod import clean as clean_lib
from clod import conversations as conversations_lib
from clod import delete as delete_lib
from clod import projects as projects_lib
from clod import purge as purge_lib
from clod import rename as rename_lib
from clod import run as run_lib
from clod import tmp as tmp_lib


app = typer.Typer(no_args_is_help=True, add_completion=True)


@app.callback()
def main() -> None:
  """Tool for running Claude Code and managing its projects and conversations."""


@app.command()
def run(
  directory: Annotated[
    pathlib.Path,
    typer.Option("--dir", "-d", help="Project to run in."),
  ] = pathlib.Path(),
  new: Annotated[
    bool,
    typer.Option("--new", "-N", help="Start a new conversation."),
  ] = False,
) -> None:
  """Run Claude Code in a project, continuing its last conversation."""
  run_lib.run(directory, new=new)


@app.command()
def conversations(
  project: Annotated[pathlib.Path, typer.Argument()] = pathlib.Path(),
  prompts: Annotated[
    bool,
    typer.Option("--prompts", "-p", help="Print the prompts typed."),
  ] = False,
) -> None:
  """List and summarize the conversations of a given project."""
  conversations_lib.run(project, show_prompts=prompts)


@app.command()
def projects() -> None:
  """List projects."""
  projects_lib.run()


@app.command()
def clean(
  yes: Annotated[
    bool,
    typer.Option("--yes", "-y", help="Delete without asking."),
  ] = False,
  dry_run: Annotated[
    bool,
    typer.Option("--dry-run", "-n", help="Only list what would be deleted."),
  ] = False,
) -> None:
  """Delete state that no longer refers to anything."""
  clean_lib.run(yes=yes, dry_run=dry_run)


@app.command()
def delete(
  ids: Annotated[
    list[str],
    typer.Argument(help="Ids of the conversations, or the start of each."),
  ],
  yes: Annotated[
    bool,
    typer.Option("--yes", "-y", help="Delete without asking."),
  ] = False,
  dry_run: Annotated[
    bool,
    typer.Option("--dry-run", "-n", help="Only list what would be deleted."),
  ] = False,
) -> None:
  """Delete conversations, of any project."""
  delete_lib.run(ids, yes=yes, dry_run=dry_run)


@app.command()
def purge(
  project: Annotated[pathlib.Path, typer.Argument()] = pathlib.Path(),
  yes: Annotated[
    bool,
    typer.Option("--yes", "-y", help="Purge without asking."),
  ] = False,
  dry_run: Annotated[
    bool,
    typer.Option("--dry-run", "-n", help="Only list what would be purged."),
  ] = False,
) -> None:
  """Delete everything Claude Code has stored about a given project."""
  purge_lib.run(project, yes=yes, dry_run=dry_run)


@app.command()
def tmp() -> None:
  """Run Claude Code in a new temporary project."""
  tmp_lib.run()


@app.command()
def rename(
  conversation: Annotated[
    str,
    typer.Argument(help="Id of the conversation, or the start of it."),
  ],
  name: Annotated[
    str | None,
    typer.Option(
      "--name", "-m", help="New name, which is asked for if left out."
    ),
  ] = None,
) -> None:
  """Rename a conversation, of any project."""
  rename_lib.run(conversation, name)
