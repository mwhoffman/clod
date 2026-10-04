"""Command line interface for cmgr."""

import pathlib
from typing import Annotated

import typer

from cmgr import clean as clean_lib
from cmgr import conversations as conversations_lib
from cmgr import delete as delete_lib
from cmgr import projects as projects_lib
from cmgr import purge as purge_lib
from cmgr import tmp as tmp_lib


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
  """Tool for managing local Claude Code projects and conversations."""


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
