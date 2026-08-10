"""Deploys register_tools.sql's UC functions from this machine via the SDK,
instead of pasting the file into a Databricks SQL editor.

Reads Lakebase credentials from ../.env (gitignored) and substitutes them
into the {{LAKEBASE_HOST}} / {{LAKEBASE_USER}} / {{LAKEBASE_PASSWORD}}
placeholders in register_tools.sql before sending each statement -- the
literal password is never written to the tracked .sql file.

Usage:
    python register_tools_cli.py --profile surge-exposure
"""
import argparse
import os
import re

from databricks.sdk import WorkspaceClient

SQL_FILE = os.path.join(os.path.dirname(__file__), "register_tools.sql")
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


def load_env(path: str) -> dict:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def split_statements(sql: str) -> list[str]:
    """Split on semicolons that are not inside a $$ ... $$ Python UDF body."""
    statements, buf, in_dollar = [], [], False
    i = 0
    while i < len(sql):
        if sql[i:i + 2] == "$$":
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        if sql[i] == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(sql[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def strip_comments(sql: str) -> str:
    """Drop full-line `--` comments outside of $$ bodies (they're just
    prose in this file, not part of any statement)."""
    out_lines = []
    in_dollar = False
    for line in sql.splitlines():
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        if not in_dollar and line.strip().startswith("--"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "surge-exposure"))
    parser.add_argument("--warehouse-id", default=None, help="Defaults to the first warehouse found.")
    args = parser.parse_args()

    env = load_env(ENV_FILE)
    with open(SQL_FILE, encoding="utf-8") as f:
        sql = f.read()

    sql = sql.replace("{{LAKEBASE_HOST}}", env["LAKEBASE_HOST"])
    sql = sql.replace("{{LAKEBASE_USER}}", env["LAKEBASE_USER"])
    sql = sql.replace("{{LAKEBASE_PASSWORD}}", env["LAKEBASE_PASSWORD"])
    sql = strip_comments(sql)

    w = WorkspaceClient(profile=args.profile)
    warehouse_id = args.warehouse_id or next(iter(w.warehouses.list())).id
    print(f"Using warehouse {warehouse_id}")

    # Each execute_statement call is its own stateless session -- a `USE
    # CATALOG`/`USE SCHEMA` in one call does not carry over to the next, so
    # skip those and pass catalog/schema explicitly on every call instead
    # (confirmed the hard way: functions silently landed in workspace.default).
    functions_registered = 0
    for stmt in split_statements(sql):
        first_line = stmt.strip().splitlines()[0][:80]
        if first_line.upper().startswith(("USE CATALOG", "USE SCHEMA")):
            continue
        print(f"Running: {first_line} ...")
        resp = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id, statement=stmt, wait_timeout="30s",
            catalog="workspace", schema="surge_exposure",
        )
        if resp.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"Statement failed: {resp.status.error}\n\nStatement was:\n{stmt}")
        if first_line.upper().startswith("CREATE OR REPLACE FUNCTION"):
            functions_registered += 1
    print(f"\nAll {functions_registered} UC functions registered under workspace.surge_exposure.")


if __name__ == "__main__":
    main()
