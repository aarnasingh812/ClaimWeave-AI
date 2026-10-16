"""Build reviewed PDF/ZIP submission artifacts deterministically, using original insurer forms."""
import io
import json
import re
import zipfile
from html import escape
from pathlib import Path
import fitz
from PIL import Image, ImageOps
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from app.core.config import settings
from app.forms import prefilled_form
from app.health import guidance_for
from app.documents import fingerprint


def safe_name(value):
    return re.sub(r'[^A-Za-z0-9._-]+', '-', Path(value.replace('\\', '/')).name)[:100] or 'document'


def summary_pdf(claim, prep, attachments=None) -> bytes:
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='SmallWrap', parent=styles['BodyText'], fontSize=8, leading=11, wordWrap='CJK'))
    story = []

    def paragraph(text, style='BodyText'):
        content = [Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style]), Spacer(1, 3 * mm)]
        if not style.startswith('Heading') and len(story) >= 2 and isinstance(story[-2], Paragraph) and story[-2].style.name.startswith('Heading'):
            heading = story[-2:]
            del story[-2:]
            story.append(KeepTogether(heading + content))
        else:
            story.extend(content)

    def table(rows, widths):
        cells = [[Paragraph(escape(str(cell)), styles['SmallWrap']) for cell in row] for row in rows]
        grid = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
        grid.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaf0fb')),
                                 ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#16305d')),
                                 ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#dae2ee')),
                                 ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7),
                                 ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
        story.append(grid)
        story.append(Spacer(1, 5 * mm))

    paragraph('ClaimWeave - Health claim submission guide', 'Title')
    paragraph('Reviewed preparation for manual submission' if prep.get('approved_revision') == claim.revision else 'DRAFT - review before submission', 'Heading2')
    paragraph(f'Claim: {claim.id} | Revision: {claim.revision} | Insurer: {claim.insurer}')
    paragraph('This pack has not been submitted. It does not determine coverage or approval. Complete and sign the claimant declaration and obtain the required hospital/doctor signatures and stamps on the official form.')
    paragraph('Confirmed claim details', 'Heading2')
    table([['Field', 'Value']] + [[key.replace('_', ' ').title(), value or 'Not provided']
                                 for key, value in prep.get('form_draft', {}).items()], [65 * mm, 111 * mm])
    paragraph('Actions before submitting', 'Heading2')
    for task in prep.get('form_status', {}).get('manual_tasks', []):
        paragraph('- ' + task)
    paragraph('- Inspect the outgoing PDF copies for legibility and page completeness. Copies use a conservative 5 MB limit; confirm the current insurer portal rules. Untouched originals are included separately.')
    unanswered = prep.get('form_status', {}).get('unanswered_mapped_fields', [])
    if unanswered:
        paragraph('Unanswered mapped fields: ' + ', '.join(key.replace('_', ' ') for key in unanswered))
    paragraph('Document index', 'Heading2')
    rows = [['No.', 'Document', 'Category', 'Pages / portal copies']]
    for index, document in enumerate(prep.get('extracted_documents', []), start=1):
        files = (attachments or {}).get(document['document_id'], [])
        rows.append([str(index), document['filename'], document['document_type'],
                     ', '.join(files) if files else str(document.get('page_count', 0))])
    table(rows, [10 * mm, 63 * mm, 40 * mm, 63 * mm])
    paragraph('Checklist and conditional answers', 'Heading2')
    table([['Requirement', 'Status / origin']] + [[item['name'], item.get('status', 'unknown') + ' / ' + item.get('origin', 'policy')]
                                               for item in prep.get('planned_requirements', [])], [116 * mm, 60 * mm])
    if prep.get('validation', {}).get('warnings'):
        paragraph('Items to check', 'Heading2')
        for warning in prep['validation']['warnings']:
            paragraph('- ' + warning)
    guide = guidance_for(claim.insurer)
    if guide:
        paragraph('Official submission instructions', 'Heading2')
        paragraph(guide['submission']['text'])
        for timeline in guide['timelines']:
            if timeline['route'] in ('all', 'reimbursement'):
                paragraph(timeline['label'] + ': ' + timeline['text'])
        for link in guide['links']:
            paragraph(link['label'] + ': ' + link['url'], 'SmallWrap')
        paragraph(f"Guidance checked: {guide['last_checked']} | Version: {guide['version']}", 'SmallWrap')
    selected = prep.get('selected_template')
    if selected:
        paragraph('Official form source: ' + selected['url'], 'SmallWrap')
        paragraph('Template version: ' + selected['version'] + ' | SHA-256: ' + selected['sha256'], 'SmallWrap')

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#687993'))
        canvas.drawString(18 * mm, 12 * mm, 'ClaimWeave | Manual submission | Complete signatures and hospital sections')
        canvas.drawRightString(194 * mm, 12 * mm, f'Page {document.page}')
        canvas.restoreState()

    SimpleDocTemplate(output, pagesize=(210 * mm, 297 * mm), leftMargin=17 * mm, rightMargin=17 * mm,
                      topMargin=18 * mm, bottomMargin=22 * mm).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def pdf_copy(path: Path) -> bytes:
    if path.suffix.lower() == '.pdf':
        return path.read_bytes()
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((2600, 2600))
        output = io.BytesIO()
        image.save(output, 'PDF', resolution=160.0)
        return output.getvalue()


def portal_copies(data: bytes, maximum: int) -> list[bytes]:
    if len(data) <= maximum:
        return [data]
    with fitz.open(stream=data, filetype='pdf') as source:
        # Cryptographic signatures must not be broken by splitting or recompression.
        if any(widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE and widget.field_value
               for page in source for widget in page.widgets() or []):
            raise ValueError('A digitally signed PDF exceeds the portal limit. Submit the original through an insurer-approved channel.')
        parts, current = [], fitz.open()
        for index, page in enumerate(source):
            single = fitz.open()
            single.insert_pdf(source, from_page=index, to_page=index)
            single_bytes = single.tobytes(garbage=3, deflate=True)
            if len(single_bytes) > maximum:
                # Re-render only the oversized outgoing COPY. The original is retained in the ZIP.
                pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
                jpg = pix.tobytes('jpeg', jpg_quality=85)
                single = fitz.open()
                target = single.new_page(width=page.rect.width, height=page.rect.height)
                target.insert_image(target.rect, stream=jpg)
                single_bytes = single.tobytes(garbage=3, deflate=True)
                if len(single_bytes) > maximum:
                    raise ValueError('A page still exceeds the portal limit; provide a smaller clear copy.')
            trial = fitz.open()
            if len(current):
                trial.insert_pdf(current)
            trial.insert_pdf(single)
            if len(current) and len(trial.tobytes(garbage=3, deflate=True)) > maximum:
                parts.append(current.tobytes(garbage=3, deflate=True))
                current = single
            else:
                current = trial
        if len(current):
            parts.append(current.tobytes(garbage=3, deflate=True))
    return parts


def submission_pack(claim, documents) -> bytes:
    prep = claim.preparation
    output, attachments, files = io.BytesIO(), {}, {}
    guide = guidance_for(claim.insurer)
    limit = 5 * 1024 * 1024
    for index, document in enumerate(documents, start=1):
        path = settings.storage_dir / document.storage_key
        if document.content_hash and fingerprint(path) != document.content_hash:
            raise ValueError('A stored document changed outside the claim workflow. Replace and reanalyze it before export.')
        basename = f'{index:02d}-{safe_name(document.original_filename)}'
        files['originals/' + basename] = path.read_bytes()
        parts = portal_copies(pdf_copy(path), limit)
        names = []
        for part_index, part in enumerate(parts, start=1):
            filename = f'attachments/{index:02d}-{document.document_type}-part-{part_index:02d}.pdf'
            files[filename] = part
            names.append(filename)
        attachments[document.id] = names
    files['00-submission-guide.pdf'] = summary_pdf(claim, prep, attachments)
    files['01-prefilled-claim-form.pdf'] = prefilled_form(prep['selected_template'], prep['form_draft'])
    files['02-confirmed-field-review.json'] = json.dumps({'revision': claim.revision,
             'documents': prep['extracted_documents'], 'conditions': prep.get('condition_answers', {})}, indent=2).encode()
    files['03-manifest.json'] = json.dumps({'claim_id': claim.id, 'revision': claim.revision,
             'status': 'prepared_for_manual_submission', 'not_submitted': True, 'portal_copy_limit_bytes': limit,
             'limit_basis': 'Niva Bupa published 5 MB limit' if guide and guide['id'] == 'niva-bupa' else 'Conservative 5 MB copy limit; confirm the current insurer portal limits',
             'template': prep['selected_template'], 'attachments': attachments,
             'note': 'Official form remains editable and unsigned. Complete declarations and hospital/doctor sections before submission.'}, indent=2).encode()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()
