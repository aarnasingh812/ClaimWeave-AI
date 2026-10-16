"""Verified insurer templates with deterministic, editable prefills. No LLM calls."""
import hashlib
import json
from pathlib import Path
from datetime import date
from decimal import Decimal, InvalidOperation
import fitz
from app.health import guidance_for

ASSETS = Path(__file__).with_name('assets') / 'forms'

# Coordinates are PDF points (top-left origin), reviewed against pinned template renders.
# Hospital declarations and signatures are intentionally never filled by the assistant.
POSITIONS = {
    'star-health': {
        'policy_number': (0, (158, 305, 305, 322)), 'policyholder_name': (0, (158, 326, 305, 341)),
        'policy_period': (0, (419, 305, 566, 322)), 'address': (0, (158, 406, 305, 422)),
        'city': (0, (419, 406, 566, 422)), 'contact_email': (0, (158, 425, 305, 441)),
        'contact_phone': (0, (158, 445, 305, 461)), 'state': (0, (419, 445, 566, 461)),
        'pincode': (0, (419, 465, 566, 480)), 'patient_name': (0, (158, 508, 305, 524)),
        'gender': (0, (419, 508, 566, 524)), 'date_of_birth': (0, (158, 529, 305, 546)),
        'relationship': (0, (419, 528, 566, 546)), 'claimed_amount': (1, (169, 60, 296, 74)),
        'total_claimed_amount': (1, (169, 134, 296, 147)),
        'bank_name': (1, (96, 552, 209, 572)), 'bank_branch': (1, (96, 577, 209, 594)),
        'bank_account_holder': (1, (270, 552, 383, 572)), 'bank_account_number': (1, (445, 577, 557, 594)),
        'ifsc_code': (1, (445, 552, 557, 572)),
    },
    'hdfc-ergo-hospitalization': {
        'policy_number': (0, (101, 174, 191, 186)),
        'policy_start_date': (0, (296, 174, 384, 186)), 'policy_end_date': (0, (463, 174, 548, 186)),
        'policyholder_name': (0, (147, 245, 548, 257)), 'contact_email': (0, (79, 271, 380, 283)),
        'contact_phone': (0, (461, 271, 548, 283)), 'occupation': (0, (91, 284, 380, 296)),
        'address': (0, (120, 298, 548, 310)), 'diagnosis': (0, (80, 311, 548, 323)),
        'patient_name': (0, (126, 346, 548, 358)), 'relationship': (0, (410, 360, 548, 372)),
        'claimed_amount': (0, (202, 471, 319, 482)), 'total_claimed_amount': (0, (463, 522, 548, 534)),
    },
    'hdfc-ergo-optima': {
        'policy_number': (0, (71, 156, 194, 169)), 'policyholder_name': (0, (71, 172, 566, 184)),
        'address': (0, (71, 187, 566, 198)), 'contact_phone': (0, (104, 217, 225, 228)),
        'contact_email': (0, (260, 217, 566, 228)), 'patient_name': (0, (103, 375, 566, 385)),
        'contact_email_2': (0, (102, 475, 566, 486)), 'hospital_name': (0, (145, 512, 566, 523)),
        'claimed_amount': (0, (176, 664, 302, 679)),
        'date_of_birth': (0, (103, 403, 224, 415)),
        'admission_date': (0, (380, 555, 483, 568)), 'discharge_date': (0, (98, 570, 183, 583)),
        'bank_account_number': (1, (370, 483, 562, 495)), 'bank_name': (1, (135, 498, 248, 509)),
        'ifsc_code': (1, (108, 513, 249, 527)), 'pan': (1, (78, 483, 248, 495)),
    },
    'care-health': {
        'policy_number': (1, (95, 190, 553, 202)), 'policyholder_name': (1, (95, 225, 553, 238)),
        'address': (1, (95, 256, 553, 267)), 'city': (1, (370, 295, 553, 306)),
        'state': (1, (95, 312, 381, 323)), 'pincode': (1, (469, 312, 553, 323)),
        'contact_phone': (1, (95, 329, 236, 340)), 'contact_email': (1, (95, 346, 553, 357)),
        'patient_name': (1, (80, 591, 553, 605)), 'hospital_name': (2, (184, 58, 556, 70)),
        'date_of_birth': (1, (425, 620, 553, 635)), 'intimation_number': (1, (466, 154, 573, 166)),
        'admission_date': (2, (151, 132, 254, 145)), 'discharge_date': (2, (151, 151, 254, 164)),
        'claimed_amount': (2, (183, 306, 255, 320)), 'bank_account_number': (3, (147, 307, 560, 321)),
        'bank_name': (3, (147, 326, 553, 338)), 'ifsc_code': (3, (147, 358, 560, 372)),
        'pan': (3, (147, 292, 560, 304)),
    },
}
NIVA_FIELDS = {
    'policy_number': 'a Policy No', 'policyholder_name': 'Name', 'patient_name': 'Name 2',
    'address': 'e Address', 'city': 'City', 'state': 'State', 'pincode': 'Pin Code',
    'contact_phone': 'Phone No', 'contact_email': 'Email', 'hospital_name': 'a Name of Hospital where Admitted',
    'date_of_birth': 'scassfd_af_date',
    'admission_date': 'datea_af_date', 'discharge_date': 'dateaaa_af_date',
    'bank_account_number': 'b Account Number', 'bank_name': 'c Bank Name and Branch',
    'ifsc_code': 'e IFSC Code', 'pan': 'a PAN',
    'claimed_amount': 'ii Hospitalization Expenses Rs',
}


def manifest():
    path = ASSETS / 'manifest.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def templates_for(insurer):
    guide = guidance_for(insurer)
    return [item for item in manifest() if guide and item['insurer_id'] == guide['id']]


def template_for(insurer, identifier=None, policy_name=''):
    items = templates_for(insurer)
    if identifier:
        return next((item for item in items if item['id'] == identifier), None)
    if 'optima' in policy_name.casefold():
        return next((item for item in items if item['id'] == 'hdfc-ergo-optima'), items[0] if items else None)
    return items[0] if items else None


def formatted(key, value):
    if key in ('claimed_amount', 'total_claimed_amount'):
        try:
            return format(Decimal(str(value)).normalize(), 'f')
        except InvalidOperation:
            return str(value)
    if key.endswith('_date') or key == 'date_of_birth':
        try:
            return date.fromisoformat(str(value)).strftime('%d/%m/%Y')
        except ValueError:
            return str(value)
    return str(value)


def mapped_value(key, values):
    if key == 'contact_email_2':
        return values.get('contact_email')
    if key == 'total_claimed_amount':
        return values.get('claimed_amount')
    if key == 'policy_period':
        if values.get('policy_start_date') and values.get('policy_end_date'):
            return formatted('policy_start_date', values['policy_start_date']) + ' - ' + formatted('policy_end_date', values['policy_end_date'])
        return None
    return values.get(key)


def fitting_font(value, rectangle):
    width = fitz.get_text_length(str(value), fontname='helv', fontsize=8)
    size = min(8, 8 * (fitz.Rect(rectangle).width - 4) / max(width, 1))
    if size < 6:
        raise ValueError('This value is too long for the form box. Use a concise form value or complete the field manually.')
    return size


def form_status(template, values):
    keys = NIVA_FIELDS if template['id'] == 'niva-bupa' else POSITIONS.get(template['id'], {})
    prefilled = [key for key in keys if mapped_value(key, values)]
    overflow = []
    if template['id'] == 'niva-bupa':
        with fitz.open(ASSETS / template['filename']) as doc:
            rectangles = {widget.field_name: widget.rect for page in doc for widget in page.widgets() or []}
        for key, name in keys.items():
            value = mapped_value(key, values)
            if value and name in rectangles:
                try:
                    fitting_font(formatted(key, value), rectangles[name])
                except ValueError:
                    overflow.append(key)
    else:
        for key, (_, rectangle) in keys.items():
            value = mapped_value(key, values)
            if value:
                try:
                    fitting_font(formatted(key, value), rectangle)
                except ValueError:
                    overflow.append(key)
    return {'prefilled_fields': prefilled, 'unanswered_mapped_fields': [key for key in keys if key not in prefilled],
            'manual_tasks': ['Review all prefilled values and unanswered insurance-history questions.',
                             'Complete the claimant declaration, signature, place and date yourself.',
                             'Ask the hospital/doctor to complete and stamp their sections or medical certificate.',
                             'Keep the original bills, receipts and records for the insurer.'],
            'overflow_fields': overflow, 'template_version': template['version'], 'source_url': template['url']}


def prefilled_form(template, values) -> bytes:
    path = ASSETS / template['filename']
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != template['sha256']:
        raise ValueError('The insurer template changed. Reverify mappings before using it.')
    if template['id'] == 'niva-bupa':
        from pypdf import PdfReader, PdfWriter
        import io
        reader = PdfReader(io.BytesIO(data))
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        # Original templates can ship with default NO answers. Unknown insurance-history
        # questions must remain unanswered; clear logical values and widget states together.
        buttons = {name: '/Off' for name, item in (reader.get_fields() or {}).items() if item.get('/FT') == '/Btn'}
        writer.update_page_form_field_values(None, buttons, auto_regenerate=False)
        from pypdf.generic import (NameObject, DictionaryObject, DecodedStreamObject, ArrayObject, FloatObject)
        for pdf_page in writer.pages:
            for ref in pdf_page.get('/Annots', []):
                annotation = ref.get_object()
                parent = annotation.get('/Parent')
                owner = parent.get_object() if parent else annotation
                if owner.get('/FT') != '/Btn':
                    continue
                rect = annotation['/Rect']
                width, height = float(rect[2] - rect[0]), float(rect[3] - rect[1])
                radio = int(owner.get('/Ff', 0)) & (1 << 15)
                if radio:
                    cx, cy, radius = width / 2, height / 2, min(width, height) / 2 - 1
                    k = radius * 0.55228475
                    shape = (f'{cx+radius} {cy} m {cx+radius} {cy+k} {cx+k} {cy+radius} {cx} {cy+radius} c '
                             f'{cx-k} {cy+radius} {cx-radius} {cy+k} {cx-radius} {cy} c '
                             f'{cx-radius} {cy-k} {cx-k} {cy-radius} {cx} {cy-radius} c '
                             f'{cx+k} {cy-radius} {cx+radius} {cy-k} {cx+radius} {cy} c S')
                else:
                    shape = f'1 1 {width-2} {height-2} re S'
                blank = DecodedStreamObject()
                blank.set_data((f'q 1 1 1 rg 0 0 {width} {height} re f 0 0 0 RG .8 w ' + shape + ' Q').encode())
                blank.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                              NameObject('/BBox'): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)]),
                              NameObject('/Resources'): DictionaryObject()})
                appearance = annotation.get('/AP', DictionaryObject()).get_object()
                states = appearance.get('/N', DictionaryObject()).get_object()
                states[NameObject('/Off')] = writer._add_object(blank)
                appearance[NameObject('/N')] = states
                annotation[NameObject('/AP')] = appearance
                annotation[NameObject('/AS')] = NameObject('/Off')
        cleared = io.BytesIO()
        writer.write(cleared)
        data = cleared.getvalue()
    doc = fitz.open(stream=data, filetype='pdf')
    if template['id'] == 'niva-bupa':
        expected = {name: formatted(key, values[key]) for key, name in NIVA_FIELDS.items() if values.get(key)}
        found = set()
        for page in doc:
            for widget in page.widgets() or []:
                if widget.field_name in expected:
                    widget.field_value = expected[widget.field_name]
                    widget.field_flags &= ~fitz.PDF_TX_FIELD_IS_COMB
                    widget.text_maxlen = 0
                    widget.text_fontsize = fitting_font(expected[widget.field_name], widget.rect)
                    widget.update()
                    found.add(widget.field_name)
        if found != set(expected):
            raise ValueError('A mapped insurer form field is missing. Reverify the template.')
    else:
        for key, (page_index, rectangle) in POSITIONS.get(template['id'], {}).items():
            value = mapped_value(key, values)
            if not value:
                continue
            widget = fitz.Widget()
            widget.field_name = 'claimweave_' + key
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect = fitz.Rect(rectangle)
            widget.field_value = formatted(key, value)
            widget.text_font = 'Helv'
            widget.text_fontsize = fitting_font(formatted(key, value), rectangle)
            widget.text_color = (0.05, 0.12, 0.25)
            widget.fill_color = (1, 1, 1)
            widget.border_width = 0
            doc[page_index].add_widget(widget)
    result = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    # Canonical AcroForm values and appearances must agree; never deliver a visual-only overlay.
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(result))
    fields = reader.get_fields() or {}
    if template['id'] == 'niva-bupa':
        required = expected
    else:
        required = {'claimweave_' + key: formatted(key, mapped_value(key, values)) for key in POSITIONS.get(template['id'], {}) if mapped_value(key, values)}
    for name, value in required.items():
        if name not in fields or str(fields[name].get('/V', '')) != value:
            raise ValueError('Prefilled form field integrity check failed for ' + name)
    return result
