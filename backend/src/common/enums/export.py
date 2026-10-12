"""File formats a history listing can be downloaded as."""

from enum import StrEnum


class ExportFormatEnum(StrEnum):
    csv = "csv"
    xlsx = "xlsx"
