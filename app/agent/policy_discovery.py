"""Best-effort official-site discovery. Never trust arbitrary links as policy evidence.

Only an explicitly allowlisted insurer domain may be downloaded. The search engine is
not authoritative; the user must confirm the result. This demo's DNS check is not
sufficient protection against all DNS rebinding; use a hardened egress proxy in prod.
"""
from urllib.parse import urlencode, urlsplit
import ipaddress
import socket
import xml.etree.ElementTree as ET
import httpx
from app.health import guidance_for
from fastapi import HTTPException

# Conservative registry. Extend after independently verifying each insurer domain.
OFFICIAL_DOMAINS = {
    'star health': ('starhealth.in',),
    'icici lombard': ('icicilombard.com',),
    'hdfc ergo': ('hdfcergo.com',),
    'niva bupa': ('nivabupa.com',),
    'care health': ('careinsurance.com',),
    'bajaj allianz': ('bajajallianz.com',),
    'new india assurance': ('newindia.co.in',),
}
MAX_BYTES = 10 * 1024 * 1024

def domains_for(insurer: str) -> tuple[str, ...]:
    key = insurer.strip().lower()
    guidance = guidance_for(insurer)
    if guidance:
        key = guidance['name'].lower()
    return OFFICIAL_DOMAINS.get(key, ())

def validated_url(url: str, domains: tuple[str, ...]) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError('Only HTTPS links without credentials or custom ports are allowed')
        if not any(host == domain or host.endswith('.' + domain) for domain in domains):
            raise ValueError('Not on the verified insurer domain allowlist')
        # Fail closed on private, loopback, link-local, reserved and mixed DNS results.
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Destination is not public')
        return url
    except (OSError, ValueError) as exc:
        raise HTTPException(422, f'Unsafe or unapproved source URL: {exc}') from exc

def discover(insurer: str, policy_name: str) -> list[dict]:
    domains = domains_for(insurer)
    if not domains:
        return []
    results = []
    for domain in domains:
        query = f'site:{domain} "{policy_name[:100]}" filetype:pdf policy wording'
        rss = 'https://www.bing.com/search?' + urlencode({'q': query, 'format': 'rss'})
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                response = client.get(rss)
                response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall('./channel/item'):
                title = (item.findtext('title') or '')[:250]
                url = (item.findtext('link') or '').strip()
                if not urlsplit(url).path.lower().endswith('.pdf'):
                    continue
                try:
                    validated_url(url, domains)
                except HTTPException:
                    continue
                if url not in {r['url'] for r in results}:
                    results.append({'title': title, 'url': url, 'domain': domain, 'verified': False})
                if len(results) >= 8:
                    return results
        except (httpx.HTTPError, ET.ParseError):
            continue
    return results

def download_official_pdf(url: str, insurer: str) -> bytes:
    domains = domains_for(insurer)
    if not domains:
        raise HTTPException(422, 'Insurer has no configured verified official domains')
    validated_url(url, domains)
    # HTTPS redirects disabled; re-checking DNS is only defense-in-depth, not a DNS pin.
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', url) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes(65536):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise HTTPException(413, 'Online policy exceeds 10 MB')
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Could not retrieve official policy PDF') from exc
    if not data.startswith(b'%PDF-'):
        raise HTTPException(422, 'Source is not a PDF; upload a policy manually')
    return bytes(data)
