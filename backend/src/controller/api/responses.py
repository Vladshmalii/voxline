"""Response builders shared by more than one router."""

import os

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from src.application.services.export import ExportFile


def export_response(file: ExportFile) -> FileResponse:
    """Send a finished export as a download, deleting it once sent."""
    return FileResponse(
        file.path,
        media_type=file.media_type,
        filename=file.filename,
        background=BackgroundTask(os.unlink, file.path),
    )
