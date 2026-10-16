import os
import uuid
import hashlib
import io
from pathlib import Path
from fastapi import HTTPException, UploadFile
from app.core.config import settings
from PIL import Image

PDF_MAGIC = b"%PDF-"

ALLOWED_EXTENSIONS = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.tif': 'image/tiff', '.tiff': 'image/tiff'}


async def save_document(upload: UploadFile, claim_id: str) -> tuple[str, int, str, str]:
    extension = Path(upload.filename or '').suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, 'Upload PDF, JPG, PNG or TIFF files')
    folder = settings.storage_dir / claim_id
    folder.mkdir(parents=True, exist_ok=True)
    key = f'{claim_id}/{uuid.uuid4().hex}{extension}'
    path = settings.storage_dir / key
    digest, size = hashlib.sha256(), 0
    try:
        with path.open('xb') as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, 'File exceeds the 10 MB upload limit')
                out.write(chunk)
                digest.update(chunk)
        if extension == '.pdf':
            with path.open('rb') as stream:
                if stream.read(5) != PDF_MAGIC:
                    raise HTTPException(415, 'Invalid PDF file')
        else:
            try:
                with Image.open(path) as image:
                    if image.format not in ('JPEG', 'PNG', 'TIFF') or image.width * image.height > 40_000_000:
                        raise ValueError('Unsupported image or image too large')
                    if getattr(image, 'n_frames', 1) != 1:
                        raise ValueError('Multi-page TIFF is not supported; upload individual pages or a PDF')
                    image.verify()
            except Exception:
                raise HTTPException(415, 'Invalid image. Upload a single JPG, PNG or TIFF page (maximum 40 megapixels).')
        return key, size, ALLOWED_EXTENSIONS[extension], digest.hexdigest()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

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
