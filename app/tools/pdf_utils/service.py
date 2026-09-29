import multiprocessing
import os
import threading
from io import BytesIO


_PDF_TIMEOUT = 10
_PDF_SLOT = threading.BoundedSemaphore(1)


def _pdf_worker(sender, body, start_page, max_pages, max_chars):
    try:
        if os.name == "posix":
            import resource

            memory = 160 * 1024 * 1024
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            capped = memory if soft == resource.RLIM_INFINITY else min(soft, memory)
            resource.setrlimit(resource.RLIMIT_AS, (capped, hard))
            resource.setrlimit(resource.RLIMIT_CPU, (6, 6))

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        page_count = len(reader.pages)
        if page_count > 1000:
            raise ValueError("PDF exceeds the 1000-page limit")
        if start_page > page_count:
            raise ValueError("start_page exceeds the PDF page count")
        pages = []
        remaining = max_chars
        last_page = min(page_count, start_page + max_pages - 1)
        truncated = False
        for number in range(start_page, last_page + 1):
            page = reader.pages[number - 1]
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > 4_000_000:
                raise ValueError("PDF page content exceeds the 4 MB processing limit")
            value = page.extract_text() or ""
            pages.append({"number": number, "text": value[:remaining]})
            remaining -= min(len(value), remaining)
            if len(value) > len(pages[-1]["text"]):
                truncated = True
                break
            if remaining == 0:
                truncated = number < page_count
                break
        sender.send({"page_count": page_count, "pages": pages,
                     "truncated": truncated or pages[-1]["number"] < page_count,
                     "scanned_possible": all(not page["text"].strip() for page in pages)})
    except Exception as error:
        sender.send({"error": f"PDF extraction failed: {str(error)[:300]}"})
    finally:
        sender.close()


def extract_pdf(body, start_page, max_pages, max_chars):
    if b"%PDF-" not in body[:1024]:
        raise ValueError("Response is not a PDF")
    if not _PDF_SLOT.acquire(blocking=False):
        raise ValueError("PDF extraction is busy; retry shortly")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_pdf_worker, args=(sender, body, start_page, max_pages, max_chars))
    try:
        process.start()
        sender.close()
        if not receiver.poll(_PDF_TIMEOUT):
            raise ValueError("PDF extraction exceeded its 10-second limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return result
    except EOFError as error:
        raise ValueError("PDF extraction worker exited without a result") from error
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
        _PDF_SLOT.release()
