"""Protect Excel/LibreOffice users from formula injection in downloaded pedigree CSV.

Only escape textual data fields that can contain imported/member text. Keep
numbers, UUIDs and column names unchanged so research data stays useful.
"""
TEXT_FIELDS = frozenset({"path", "name", "sex", "colour", "country", "kennel"})


def safe_pedigree_csv_row(row):
    clean = dict(row)
    for key in TEXT_FIELDS:
        value = clean.get(key)
        if not isinstance(value, str):
            continue
        # A cell beginning with whitespace/control characters followed by a
        # formula prefix can still be interpreted as a formula by spreadsheets.
        # Prefix the ORIGINAL value with an apostrophe, including any leading
        # whitespace, so the spreadsheet treats it as literal text.
        candidate = value.lstrip(" \t\r\n\ufeff")
        if candidate.startswith(("=", "+", "-", "@")):
            clean[key] = "'" + value
    return clean


def safe_pedigree_csv_rows(rows):
    for row in rows:
        yield safe_pedigree_csv_row(row)
