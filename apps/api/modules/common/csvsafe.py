"""CSV helpers that stop spreadsheet formula execution (CRM02)."""
import csv
import io

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in DANGEROUS_PREFIXES:
        return "'" + text
    return text


def write_csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([safe_cell(c) for c in row])
    return buffer.getvalue()
