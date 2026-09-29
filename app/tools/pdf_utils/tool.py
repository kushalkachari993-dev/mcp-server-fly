import json
from functools import partial

import anyio
import urllib3

from app.tools.webpage.service import fetch_page

from .service import extract_pdf


_PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


def register(mcp):

    @mcp.tool()
    async def extract_pdf_text(url: str, start_page: int = 1, max_pages: int = 5, max_chars: int = 12000) -> str:
        """Extract text from selected pages of a public, non-encrypted PDF URL.
        Downloads at most 1 MB; processes at most 10 pages and 50000 text characters.
        Parsing is isolated with CPU, memory, and wall-time limits. Image-only PDFs
        need OCR, which this tool does not perform. Returns one-indexed page numbers.
        """
        try:
            if start_page < 1 or not 1 <= max_pages <= 10 or not 100 <= max_chars <= 50000:
                raise ValueError("start_page must be positive, max_pages 1-10, and max_chars 100-50000")
            body, _, final_url = await anyio.to_thread.run_sync(partial(fetch_page, url, media_types=_PDF_TYPES))
            result = await anyio.to_thread.run_sync(extract_pdf, body, start_page, max_pages, max_chars)
            return json.dumps({"url": final_url, **result}, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
