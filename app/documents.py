"""Local PDF/image reading and OCR. No LLM calls; all pages carry provenance."""
import hashlib
import io
import threading
from pathlib import Path
import fitz
import numpy as np
from PIL import Image, ImageOps
from app.core.config import settings

READ_VERSION = 'local-ocr-v1'
_ocr = None
_ocr_lock = threading.Lock()


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def ocr_image(image: Image.Image) -> tuple[str, float]:
    global _ocr
    from rapidocr import RapidOCR
    with _ocr_lock:
        if _ocr is None:
            _ocr = RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                                    'EngineConfig.onnxruntime.inter_op_num_threads': 1,
                                    'Global.log_level': 'warning'})
        result = _ocr(np.array(image.convert('RGB')))
    texts = list(result.txts or [])
    scores = list(result.scores or [])
    return '\n'.join(texts), float(sum(scores) / len(scores)) if scores else 0.0


def page_quality(image: Image.Image) -> list[str]:
    warnings = []
    if min(image.size) < 500:
        warnings.append('Low image resolution. Retake the full page at higher resolution.')
    gray = np.array(image.convert('L').resize((800, 800)), dtype=np.float32)
    laplacian = (gray[1:-1, 2:] + gray[1:-1, :-2] + gray[2:, 1:-1] + gray[:-2, 1:-1]
                 - 4 * gray[1:-1, 1:-1])
    if float(laplacian.var()) < 12:
        warnings.append('Page may be blurred or blank. Check legibility and page edges before confirming.')
    return warnings


def read_document(path: Path) -> dict:
    pages, errors, warnings = [], [], []
    try:
        if path.suffix.lower() == '.pdf':
            with fitz.open(path) as pdf:
                if pdf.is_encrypted:
                    raise ValueError('Encrypted PDFs are not supported; upload an unlocked copy.')
                if len(pdf) > settings.document_max_pages:
                    raise ValueError(f'Document has {len(pdf)} pages; maximum is {settings.document_max_pages}. Split it into smaller files.')
                if len(pdf) == 0:
                    raise ValueError('The PDF has no pages.')
                for index, page in enumerate(pdf):
                    text = page.get_text('text').strip()
                    method, confidence, issues = 'pdf_text', 1.0, []
                    # Image-heavy mixed pages must not lose scanned content merely because a footer has text.
                    image_area = sum(fitz.Rect(item['bbox']).get_area() for item in page.get_image_info())
                    needs_ocr = len(text) < 60 or image_area > page.rect.get_area() * 0.5
                    if needs_ocr:
                        scale = min(2.0, 2500 / max(page.rect.width, page.rect.height))
                        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                        image = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
                        ocr_text, confidence = ocr_image(image)
                        # OCR sees the whole page, so avoid duplicating headers and footers in the prompt.
                        text = ocr_text or text
                        method, issues = 'local_ocr', page_quality(image)
                    pages.append({'page': index + 1, 'text': text, 'method': method,
                                  'confidence': round(confidence, 3), 'warnings': issues})
        else:
            with Image.open(path) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                issues = page_quality(image)
                image.thumbnail((3000, 3000))
                text, confidence = ocr_image(image)
                pages.append({'page': 1, 'text': text, 'method': 'local_ocr',
                              'confidence': round(confidence, 3), 'warnings': issues})
        for page in pages:
            if len(page['text'].strip()) < 20:
                errors.append(f"Page {page['page']} has too little readable text. Retake or replace it.")
            elif page['confidence'] < settings.ocr_min_confidence:
                warnings.append(f"Page {page['page']} has low OCR confidence. Check it against the original.")
            warnings.extend(f"Page {page['page']}: {warning}" for warning in page['warnings'])
    except Exception as exc:
        errors.append(str(exc) if isinstance(exc, ValueError) else 'Could not read this file. Upload a clear, unencrypted PDF or image.')
    text = '\n\n'.join(f"[PAGE {page['page']}]\n{page['text']}" for page in pages)
    return {'reader_version': READ_VERSION, 'pages': pages, 'text': text,
            'errors': errors, 'warnings': warnings, 'page_count': len(pages)}


def preview_page(path: Path, page_number: int = 1) -> bytes:
    if path.suffix.lower() == '.pdf':
        with fitz.open(path) as pdf:
            if page_number < 1 or page_number > len(pdf):
                raise ValueError('Page not found')
            page = pdf[page_number - 1]
            scale = min(1.8, 1800 / max(page.rect.width, page.rect.height))
            return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
    if page_number != 1:
        raise ValueError('Page not found')
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((1800, 1800))
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()
