import os
from collections import defaultdict, deque

import psycopg
from psycopg import sql

SCHEMA = os.getenv("DJANGO_DB_SCHEMA", "django_app")


def table_names(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = %s
            ORDER BY tablename
            """,
            (SCHEMA,),
        )
        return [row[0] for row in cursor.fetchall()]


def copyable_columns(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND is_generated = 'NEVER'
            ORDER BY ordinal_position
            """,
            (SCHEMA, table),
        )
        return [row[0] for row in cursor.fetchall()]


def copy_order(connection, tables):
    table_set = set(tables)
    edges = defaultdict(set)
    indegree = {table: 0 for table in tables}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT child.relname, parent.relname, constraint_row.condeferrable
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS child
              ON child.oid = constraint_row.conrelid
            JOIN pg_namespace AS child_ns
              ON child_ns.oid = child.relnamespace
            JOIN pg_class AS parent
              ON parent.oid = constraint_row.confrelid
            JOIN pg_namespace AS parent_ns
              ON parent_ns.oid = parent.relnamespace
            WHERE constraint_row.contype = 'f'
              AND child_ns.nspname = %s
              AND parent_ns.nspname = %s
            """,
            (SCHEMA, SCHEMA),
        )
        constraints = cursor.fetchall()

    # Deferrable foreign keys can safely be checked at transaction commit.
    # Only non-deferrable foreign keys constrain the table copy order.
    for child, parent, deferrable in constraints:
        if deferrable or child == parent:
            continue
        if child not in table_set or parent not in table_set:
            continue
        if child not in edges[parent]:
            edges[parent].add(child)
            indegree[child] += 1

    queue = deque(sorted(table for table, degree in indegree.items() if degree == 0))
    ordered = []
    while queue:
        table = queue.popleft()
        ordered.append(table)
        for child in sorted(edges[table]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(tables):
        blocked = sorted(table for table, degree in indegree.items() if degree)
        raise RuntimeError(
            "Non-deferrable foreign-key cycle prevents safe copy: "
            + ", ".join(blocked)
        )
    return ordered


def row_counts(connection, tables):
    counts = {}
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}.{}").format(
                    sql.Identifier(SCHEMA),
                    sql.Identifier(table),
                )
            )
            counts[table] = cursor.fetchone()[0]
    return counts


def copy_table(source, target, table, columns):
    identifiers = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    export = sql.SQL("COPY {}.{} ({}) TO STDOUT").format(
        sql.Identifier(SCHEMA),
        sql.Identifier(table),
        identifiers,
    )
    load = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(SCHEMA),
        sql.Identifier(table),
        identifiers,
    )

    with source.cursor().copy(export) as source_copy:
        with target.cursor().copy(load) as target_copy:
            for chunk in source_copy:
                target_copy.write(chunk)


def sync_sequences(source, target):
    with source.cursor() as cursor:
        cursor.execute(
            """
            SELECT sequencename
            FROM pg_sequences
            WHERE schemaname = %s
            ORDER BY sequencename
            """,
            (SCHEMA,),
        )
        sequences = [row[0] for row in cursor.fetchall()]

    target_sequences = set()
    with target.cursor() as cursor:
        cursor.execute(
            """
            SELECT sequencename
            FROM pg_sequences
            WHERE schemaname = %s
            """,
            (SCHEMA,),
        )
        target_sequences = {row[0] for row in cursor.fetchall()}

    missing = sorted(set(sequences) - target_sequences)
    if missing:
        raise RuntimeError("Target is missing sequences: " + ", ".join(missing))

    for sequence in sequences:
        query = sql.SQL("SELECT last_value, is_called FROM {}.{}").format(
            sql.Identifier(SCHEMA),
            sql.Identifier(sequence),
        )
        with source.cursor() as cursor:
            cursor.execute(query)
            last_value, is_called = cursor.fetchone()

        with target.cursor() as cursor:
            cursor.execute(
                "SELECT setval(%s::regclass, %s, %s)",
                (f"{SCHEMA}.{sequence}", last_value, is_called),
            )


def main():
    source_url = os.environ["SOURCE_DATABASE_URL"]
    target_url = os.environ["TARGET_DATABASE_URL"]

    with psycopg.connect(source_url, sslmode="require") as source:
        with psycopg.connect(target_url, sslmode="require") as target:
            source_tables = table_names(source)
            target_tables = table_names(target)

            if source_tables != target_tables:
                raise SystemExit(
                    "Source/target table sets differ. "
                    f"source_only={sorted(set(source_tables) - set(target_tables))}; "
                    f"target_only={sorted(set(target_tables) - set(source_tables))}"
                )

            for table in source_tables:
                source_columns = copyable_columns(source, table)
                target_columns = copyable_columns(target, table)
                if source_columns != target_columns:
                    raise SystemExit(
                        f"Column mismatch for {table}: "
                        f"source={source_columns}; target={target_columns}"
                    )

            source_counts = row_counts(source, source_tables)
            order = copy_order(target, target_tables)

            with target.transaction():
                with target.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                    truncate_targets = sql.SQL(", ").join(
                        sql.SQL("{}.{}").format(
                            sql.Identifier(SCHEMA),
                            sql.Identifier(table),
                        )
                        for table in target_tables
                    )
                    cursor.execute(
                        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                            truncate_targets
                        )
                    )

                for table in order:
                    columns = copyable_columns(source, table)
                    copy_table(source, target, table, columns)
                    print(f"Copied {table}: {source_counts[table]} rows")

                sync_sequences(source, target)

            target_counts = row_counts(target, target_tables)
            mismatches = {
                table: (source_counts[table], target_counts[table])
                for table in source_tables
                if source_counts[table] != target_counts[table]
            }
            if mismatches:
                raise SystemExit(f"Row-count verification failed: {mismatches}")

            total_rows = sum(source_counts.values())
            print(
                f"Verified transactional copy of {len(source_tables)} tables "
                f"and {total_rows} rows."
            )


if __name__ == "__main__":
    main()
