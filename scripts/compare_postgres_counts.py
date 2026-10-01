import os
import sys

import psycopg

SCHEMA = "django_app"


def counts(database_url):
    with psycopg.connect(database_url, sslmode="require") as connection:
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
            tables = [row[0] for row in cursor.fetchall()]
            result = {}
            for table in tables:
                cursor.execute(f'SELECT count(*) FROM "{SCHEMA}"."{table}"')
                result[table] = cursor.fetchone()[0]
            return result


def main():
    source = counts(os.environ["SOURCE_DATABASE_URL"])
    target = counts(os.environ["TARGET_DATABASE_URL"])

    if set(source) != set(target):
        print("Table sets differ.", file=sys.stderr)
        print("Missing in target:", sorted(set(source) - set(target)), file=sys.stderr)
        print("Extra in target:", sorted(set(target) - set(source)), file=sys.stderr)
        raise SystemExit(1)

    mismatches = []
    for table in sorted(source):
        print(f"{table}: source={source[table]} target={target[table]}")
        if source[table] != target[table]:
            mismatches.append(table)

    if mismatches:
        print("Row-count mismatches: " + ", ".join(mismatches), file=sys.stderr)
        raise SystemExit(1)

    print(f"Verified {len(source)} Django tables with identical row counts.")


if __name__ == "__main__":
    main()
