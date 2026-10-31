"""Measure local RapidOCR on the fictional HK scans. Prints numbers only; no thresholds are claimed.

Run from the backend directory so the app package resolves:
    ..\\.venv-jiuwen\\Scripts\\python.exe ..\\scripts\\evaluate_hk_ocr.py
"""
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
from app.parsing import parse_file  # noqa: E402
from create_hk_examples import SUBLET_ZH, LEASE_EN  # noqa: E402

CASES = [
    ('sublet-zh', 'fictional-hk-scan-sublet-zh', SUBLET_ZH,
     ['二房東', '死約', '港幣6,500元', '港幣13,000元', '按金', '轉數快', '胞弟', '交吉', '印花', '不予退還', '隨時進入', '2026年12月1日']),
    ('lease-en', 'fictional-hk-scan-lease-en', LEASE_EN[:13],
     ['HK$12,000', 'HK$24,000', 'vacant possession', 'fixed term', 'Mr. Chan Example Agent', '30 November 2028', 'structural repairs',
      'forfeit the deposit', 'remainder of the fixed term', 'Government rent']),
]


def squash(text):
    # Compare content, not layout: drop whitespace and unify full/half-width punctuation.
    table = str.maketrans('，：；（）「」', ',:;()""')
    return re.sub(r'\s+', '', text).translate(table)


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def substitutions(truth, found):
    pairs = Counter()
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, truth, found, autojunk=False).get_opcodes():
        if tag == 'replace' and i2 - i1 == j2 - j1:
            pairs.update(zip(truth[i1:i2], found[j1:j2]))
    return [f'{a}->{b}×{n}' for (a, b), n in pairs.most_common(12)]


def main():
    report = []
    for name, stem, lines, terms in CASES:
        truth = squash('\n'.join(lines))
        for ext in ('png', 'pdf'):
            data = (ROOT / 'examples' / 'hk' / f'{stem}.{ext}').read_bytes()
            doc = parse_file(data, f'{stem}.{ext}')
            text = '\n'.join(b.text for b in doc.blocks)
            found = squash(text)
            report.append({'case': name, 'file': f'{stem}.{ext}', 'sources': sorted({b.source for b in doc.blocks}),
                           'chars_truth': len(truth), 'chars_ocr': len(found),
                           'cer': round(edit_distance(truth, found) / len(truth), 4),
                           'terms_found': [t for t in terms if squash(t) in found],
                           'terms_missed': [t for t in terms if squash(t) not in found],
                           'top_substitutions': substitutions(truth, found),
                           'warnings': [w for w in doc.warnings if 'OCR' in w]})
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
