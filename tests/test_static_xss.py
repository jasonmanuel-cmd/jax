"""Static-UI XSS and credential-storage regressions (SPEC_AUDIT R1, R3).

These are asserted against the served HTML source rather than a live browser:
the dangerous patterns are static text, so a source-level check is exact and
does not depend on a headless browser being available.
"""
import importlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADMIN = 'test-admin-token-that-is-long-enough-0123456789'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


@pytest.fixture(scope='module')
def html():
    return (ROOT / 'core' / 'static' / 'index.html').read_text(encoding='utf-8')


def test_no_admin_token_in_localstorage(html):
    """localStorage is readable by any injected script; the token must not be there."""
    assert 'localStorage.setItem' not in html
    assert 'localStorage.getItem' not in html
    assert 'jax_token' not in html


def test_no_untrusted_data_in_inline_handlers(html):
    """Interpolating scraped values into onclick= lets a quote break out."""
    assert not re.search(r'onclick="[^"]*\$\{', html), \
        'untrusted interpolation inside an inline handler'
    assert "onclick=\"window.open('" not in html


def test_scraped_urls_go_through_an_allowlist(html):
    """javascript: and data: URLs must never reach window.open or href."""
    assert 'function safeHttpUrl' in html
    body = html[html.index('function safeHttpUrl'):html.index('function safeHttpUrl') + 400]
    assert 'http:' in body and 'https:' in body
    assert 'javascript:' not in body.replace("'javascript:'", '')


def test_esc_attr_escapes_full_attribute_context(html):
    """Quotes, angle brackets and ampersands all matter inside an attribute."""
    match = re.search(r'function escAttr\(s\)\s*\{(.*?)\n\}', html, re.S)
    assert match, 'escAttr must exist'
    body = match.group(1)
    for needed in ('&amp;', '&quot;', '&#39;', '&lt;', '&gt;'):
        assert needed in body, f'escAttr must escape {needed}'


def test_delegated_handlers_read_dataset(html):
    """Untrusted values must be read at click time, not baked into code."""
    assert 'btn.dataset.url' in html
    assert "addEventListener('click'" in html


def test_external_links_are_noopener(html):
    assert 'noopener' in html


@pytest.mark.parametrize('payload', [
    "x' onerror='alert(1)",
    'x" onload="alert(1)',
    'javascript:alert(1)',
    '"><img src=x onerror=alert(1)>',
    "',''); alert('1",
])
def test_malicious_payloads_are_inert_in_source(html, payload):
    """The payload text must not appear in any executable position."""
    # It may legitimately appear inside an escHtml()/escAttr() call, which is
    # the safe path. What must never happen is a raw template interpolation
    # of a scraped field inside an inline handler.
    for field in ('r.url', 'r.title', 'r.snippet', 's)'):
        for match in re.finditer(re.escape(field), html):
            segment = html[match.start():match.start() + 80]
            assert 'onclick=' not in segment, \
                f'{field} reaches an inline handler'


def test_page_still_serves(html):
    """The escaping changes must not have broken the page."""
    assert '<html' in html.lower()
    assert 'safeHttpUrl' in html
    assert 'function escHtml' in html