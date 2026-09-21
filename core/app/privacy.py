"""Conservative defense in depth, not a guarantee of secret detection."""
import re
import unicodedata

DENIED = re.compile(
    r'password|bitwarden|keepass|1password|lastpass|dashlane|private[ _-]?key|seed[ _-]?phrase|'
    r'api[ _-]?key|access[ _-]?token|refresh[ _-]?token|client[ _-]?secret|authorization|'
    r'bearer\s+\S+|sk-[\w-]{16,}|gh[pousr]_[\w]{20,}|github_pat_[\w]+|'
    r'AKIA[A-Z0-9]{16}|eyJ[\w-]+\.[\w-]+\.[\w-]+', re.I)


def safe_text(value):
    normalized = unicodedata.normalize('NFKC', value)
    normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Cf')
    if DENIED.search(normalized):
        raise ValueError('Rejected by privacy policy')
    return value
