"""History exports: a filtered query, written out as one CSV or XLSX file.

Format-agnostic on purpose — the SMS and call history services each declare
their columns and hand over their rows; nothing here knows which resource it
is writing. The file is built in full on disk before the response starts, so
a failure mid-query is an error response, not a truncated download, and the
request's DB session closes the ordinary way.

Rows arrive in partitions from a server-side cursor; each partition is
converted and written in a worker thread, so a large export neither holds the
whole result in memory nor stalls the event loop.
"""

import asyncio
import csv
import os
import re
import tempfile
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

import xlsxwriter

from src.common.enums.export import ExportFormatEnum

MEDIA_TYPES = {
    ExportFormatEnum.csv: "text/csv; charset=utf-8",
    ExportFormatEnum.xlsx: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
}

#: A spreadsheet treats a cell starting with one of these as a formula —
#: SMS bodies and call summaries are caller/model text, so CSV cells get a
#: leading quote. A normalized phone number (``+380…``) is left as it is.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PHONE = re.compile(r"\+\d+")


class ExportTooLarge(ValueError):
    """More rows match than one file may hold; narrow the filters."""


@dataclass(frozen=True)
class Column:
    header: str
    value: Callable[[Any], Any]


@dataclass(frozen=True)
class ExportFile:
    path: str
    media_type: str
    filename: str


def _plain(value: Any, tz: ZoneInfo) -> Any:
    """One cell as str, int, float, naive datetime (in ``tz``) or None."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, datetime):
        # Stored naive UTC; written as wall time in the requested zone. Whole
        # seconds: Excel rounds 23:59:59.9 up to the next day on display,
        # which would move a row across the day boundary its filter used.
        local = value.replace(tzinfo=UTC).astimezone(tz)
        return local.replace(tzinfo=None, microsecond=0)
    if isinstance(value, int | float | str):
        return value
    if isinstance(value, list | tuple):
        return "; ".join(str(item) for item in value)
    return str(value)


class _CsvSink:
    def __init__(self, path: str):
        # The BOM is what makes Excel read the file as UTF-8 (Cyrillic).
        self._file = open(path, "w", encoding="utf-8-sig", newline="")  # noqa: SIM115
        self._csv = csv.writer(self._file)

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, str):
            if value.startswith(_FORMULA_START) and not _PHONE.fullmatch(value):
                return "'" + value
            return value
        return str(value)

    def header(self, headers: list[str]) -> None:
        self._csv.writerow(headers)

    def rows(self, rows: list[list[Any]]) -> None:
        self._csv.writerows([self._text(value) for value in row] for row in rows)

    def close(self) -> None:
        self._file.close()


class _XlsxSink:
    def __init__(self, path: str):
        # constant_memory flushes each row as it is written: memory stays flat
        # however many rows, at the price of writing strictly row by row.
        self._book = xlsxwriter.Workbook(path, {"constant_memory": True})
        self._sheet = self._book.add_worksheet()
        self._bold = self._book.add_format({"bold": True})
        self._when = self._book.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"})
        self._next = 0

    def header(self, headers: list[str]) -> None:
        self._sheet.set_column(0, len(headers) - 1, 18)
        self._sheet.freeze_panes(1, 0)
        for col, header in enumerate(headers):
            self._sheet.write_string(0, col, header, self._bold)
        self._next = 1

    def rows(self, rows: list[list[Any]]) -> None:
        for row in rows:
            for col, value in enumerate(row):
                if value is None:
                    continue
                if isinstance(value, datetime):
                    self._sheet.write_datetime(self._next, col, value, self._when)
                elif isinstance(value, int | float):
                    self._sheet.write_number(self._next, col, value)
                else:
                    # Never write(): it would turn "=…" text into a formula.
                    self._sheet.write_string(self._next, col, value)
            self._next += 1

    def close(self) -> None:
        self._book.close()


_SINKS = {ExportFormatEnum.csv: _CsvSink, ExportFormatEnum.xlsx: _XlsxSink}


async def write_table(
    partitions: AsyncIterator[Sequence[Any]],
    columns: Sequence[Column],
    fmt: ExportFormatEnum,
    tz: ZoneInfo,
    name: str,
    max_rows: int,
) -> ExportFile:
    """Write every row of ``partitions`` to a temporary file.

    Args:
        partitions: Row batches, in the order the file should list them.
        columns: The header and how to read each cell from a row.
        fmt: CSV or XLSX.
        tz: The zone datetimes are written in.
        name: File name stem, e.g. ``"sms"``.
        max_rows: Refuse beyond this many rows.

    Returns:
        The finished file; the caller owns it and must delete it.

    Raises:
        ExportTooLarge: More than ``max_rows`` rows matched. No file is left.
    """
    fd, path = tempfile.mkstemp(prefix=f"{name}-", suffix=f".{fmt}")
    os.close(fd)
    sink = _SINKS[fmt](path)

    def write(rows: Sequence[Any]) -> None:
        sink.rows([[_plain(c.value(row), tz) for c in columns] for row in rows])

    try:
        sink.header([c.header for c in columns])
        written = 0
        async with aclosing(partitions) as batches:
            async for rows in batches:
                written += len(rows)
                if written > max_rows:
                    raise ExportTooLarge(
                        f"more than {max_rows} rows match; narrow the filters"
                    )
                await asyncio.to_thread(write, rows)
        await asyncio.to_thread(sink.close)
    except BaseException:
        try:
            sink.close()
        finally:
            os.unlink(path)
        raise
    stamp = datetime.now(tz).strftime("%Y%m%d_%H%M")
    return ExportFile(path, MEDIA_TYPES[fmt], f"{name}_{stamp}.{fmt}")
