"""Download reviewed official blank templates once, never once per claim."""
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'assets' / 'forms'
TEMPLATES = [
    {'id': 'star-health', 'insurer_id': 'star-health', 'name': 'Star Health reimbursement form',
     'url': 'https://d28c6jni2fmamz.cloudfront.net/CLAIMFORM_89ec9742bd.pdf',
     'source_page': 'https://www.starhealth.in/claims/', 'scope': 'Health reimbursement; check exact policy and edition'},
    {'id': 'niva-bupa', 'insurer_id': 'niva-bupa', 'name': 'Niva Bupa reimbursement form',
     'url': 'https://transactions.nivabupa.com/pages/doc/claim_form/ReimbursementClaimForm.pdf',
     'source_page': 'https://transaction.nivabupa.com/claims/pages/health-claim.aspx', 'scope': 'Health reimbursement; check exact policy and edition'},
    {'id': 'care-health', 'insurer_id': 'care-health', 'name': 'Care Health reimbursement form (English)',
     'url': 'https://cms.careinsurance.com/cms/public/uploads/download_center/health-claim-form---english.pdf',
     'source_page': 'https://www.careinsurance.com/health-insurance-claim-forms.html', 'scope': 'Products listed on the official English health form downloads page; confirm your product'},
    {'id': 'hdfc-ergo-hospitalization', 'insurer_id': 'hdfc-ergo', 'name': 'HDFC ERGO hospitalization form',
     'url': 'https://customer-portal-assets.hdfcergo.com/assets/v2/docs/default-source/downloads/claim-forms/hospitalization-claim-form-410828258118.pdf',
     'source_page': 'https://www.hdfcergo.com/download/claim-form/health', 'scope': 'Hospitalization form; confirm suitability for your exact product'},
    {'id': 'hdfc-ergo-optima', 'insurer_id': 'hdfc-ergo', 'name': 'HDFC ERGO my: Optima Secure form',
     'url': 'https://customer-portal-assets.hdfcergo.com/assets/v2/docs/default-source/downloads/claim-forms/myoptima-secure---cf-58675432702.pdf',
     'source_page': 'https://www.hdfcergo.com/download/claim-form/health', 'scope': 'my: Optima Secure only; confirm product version/UIN'},
]


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(timeout=60, follow_redirects=True, headers={
            'User-Agent': 'Mozilla/5.0', 'Accept': 'application/pdf,*/*'}) as client:
        for template in TEMPLATES:
            filename = template['id'] + '.pdf'
            if (ROOT / filename).exists():
                data = (ROOT / filename).read_bytes()
            else:
                response = client.get(template['url'], headers={'Referer': template['source_page']})
                response.raise_for_status()
                data = response.content
            if not data.startswith(b'%PDF-') or len(data) > 15 * 1024 * 1024:
                raise ValueError('Unexpected template content for ' + template['id'])
            (ROOT / filename).write_bytes(data)
            manifest.append({**template, 'filename': filename, 'checked_at': '2026-10-14',
                             'sha256': hashlib.sha256(data).hexdigest(), 'version': '2026-10-14.1'})
            print(template['id'], len(data), 'bytes')
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
