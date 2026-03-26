from __future__ import annotations

import shlex

import click


def run_repl(cli: click.BaseCommand, ctx_obj: object, prog_name: str) -> None:
    click.echo("CLI-Anything Coda REPL. Type 'help' for commands and 'exit' to quit.")

    while True:
        try:
            line = input("coda> ").strip()
        except EOFError:
            click.echo()
            return
        except KeyboardInterrupt:
            click.echo()
            continue

        if not line:
            continue

        if line in {"exit", "quit"}:
            return

        if line == "help":
            click.echo("Use any normal subcommand, for example: docs list, pages list, rows get grid-1 row-1")
            continue

        try:
            args = shlex.split(line)
        except ValueError as exc:
            click.echo(f"Parse error: {exc}", err=True)
            continue

        try:
            cli.main(args=args, prog_name=prog_name, obj=ctx_obj, standalone_mode=False)
        except click.ClickException as exc:
            exc.show()
        except SystemExit as exc:
            if exc.code not in (0, None):
                click.echo(f"Command exited with status {exc.code}", err=True)
        except KeyboardInterrupt:
            click.echo()
        except Exception as exc:  # pragma: no cover
            click.echo(f"Unhandled error: {exc}", err=True)
