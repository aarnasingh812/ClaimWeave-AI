import os
import uuid
from pathlib import Path
from fastapi import HTTPException, UploadFile
from app.core.config import settings

PDF_MAGIC = b"%PDF-"

async def save_pdf(upload: UploadFile, claim_id: str) -> tuple[str, int]:
    # Never use the untrusted client filename as a filesystem path.
    folder = settings.storage_dir / claim_id
    folder.mkdir(parents=True, exist_ok=True)
    key = f"{claim_id}/{uuid.uuid4().hex}.pdf"
    path = settings.storage_dir / key
    size = 0
    try:
        with path.open("xb") as out:
            first = await upload.read(5)
            if first != PDF_MAGIC:
                raise HTTPException(415, "Only PDF files are supported")
            out.write(first)
            size += len(first)
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "File exceeds upload size limit")
                out.write(chunk)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key, size
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
