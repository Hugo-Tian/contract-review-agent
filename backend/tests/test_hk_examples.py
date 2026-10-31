"""Hong Kong edition, stage ⑤: fictional fixtures and local OCR on Traditional Chinese / English scans."""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import contract_tools
from app.main import app
from app.parsing import parse_file
from app.profiles import hk

ROOT = Path(__file__).resolve().parents[2]
HK = ROOT / 'examples' / 'hk'
sys.path.insert(0, str(ROOT / 'scripts'))
from create_hk_examples import FILES, AGENT_MESSAGES  # noqa: E402


@pytest.fixture(autouse=True)
def hong_kong(monkeypatch):
    monkeypatch.setenv('REGION', 'hk')


def text_of(doc):
    return '\n'.join(b.text for b in doc.blocks)


def test_committed_fixtures_match_generator_and_are_marked_fictional():
    for stem, lines in FILES.items():
        assert (HK / f'{stem}.txt').read_text(encoding='utf-8') == '\n'.join(lines)
        assert 'FICTIONAL' in lines[0] or '虛構' in lines[0]
    messages = (HK / 'fictional-hk-agent-messages.txt').read_text(encoding='utf-8')
    assert messages.startswith('虛構示例') and all(m in messages for m in AGENT_MESSAGES)
    assert hk.UI['sample'] == (HK / 'fictional-hk-lease-en.txt').read_text(encoding='utf-8')


@pytest.mark.parametrize('stem,needles', [
    ('fictional-hk-lease-en', ['HK$12,000', 'HK$24,000', 'Mr. Chan Example Agent', 'forfeit the deposit']),
    ('fictional-hk-temporary-en', ['within 14 days', 'The Landlord shall be responsible for repairing']),
    ('fictional-hk-sublet-zh', ['二房東', '港幣13,000元', '胞弟何示例', '按金不予退還']),
])
@pytest.mark.parametrize('ext', ['pdf', 'docx'])
def test_fixtures_parse_with_original_wording(stem, needles, ext):
    doc = parse_file((HK / f'{stem}.{ext}').read_bytes(), f'{stem}.{ext}')
    text = text_of(doc)
    assert all(n in text.replace('\n', ' ') for n in needles)
    assert all(b.source == 'file' for b in doc.blocks)


def test_hk_examples_run_through_demo_workflow():
    with TestClient(app) as client:
        for stem in FILES:
            doc = client.post('/api/documents/text', json={'text': (HK / f'{stem}.txt').read_text(encoding='utf-8')}).json()
            result = client.post('/api/workflow', json={'document_id': doc['id'], 'version': 1, 'mode': 'demo', 'confirmed': True})
            assert result.status_code == 200, result.text
            assert [f['label'] for f in result.json()['report']['facts']] == list(hk.FACT_LABELS)


def test_temporary_vs_formal_lease_shows_the_planted_differences():
    temporary = parse_file((HK / 'fictional-hk-temporary-en.docx').read_bytes(), 't.docx')
    formal = parse_file((HK / 'fictional-hk-lease-en.docx').read_bytes(), 'f.docx')
    changes = contract_tools.compare_versions(temporary, formal)['changes']
    before = ' '.join(p['text'] for c in changes for p in c['before'])
    after = ' '.join(p['text'] for c in changes for p in c['after'])
    assert 'within 14 days' in before and 'within 14 days' not in after
    assert 'The Landlord shall be responsible for repairing' in before
    assert 'responsible for all repairs, whether minor or major' in after


def test_english_scan_ocr_and_hk_warning():
    for ext in ('png', 'pdf'):
        doc = parse_file((HK / f'fictional-hk-scan-lease-en.{ext}').read_bytes(), f'scan.{ext}')
        # OCR sometimes drops the space between words; compare without whitespace, as the evaluation does.
        text = ''.join(text_of(doc).split())
        assert all(b.source == 'ocr' for b in doc.blocks)
        assert all(term.replace(' ', '') in text for term in ('vacant possession', '30 November 2028', 'structural repairs'))
        assert any('HK$' in w and '繁体' in w for w in doc.warnings)


def test_traditional_scan_ocr_finds_key_terms_but_warns(monkeypatch):
    doc = parse_file((HK / 'fictional-hk-scan-sublet-zh.png').read_bytes(), 'scan.png')
    text = text_of(doc)
    assert '二房東' in text and '按金' in text and '交吉' in text
    assert any('繁体' in w and '不予退還' in w for w in doc.warnings)
    monkeypatch.setenv('REGION', 'cn')
    doc = parse_file((HK / 'fictional-hk-scan-sublet-zh.png').read_bytes(), 'scan.png')
    assert not any('繁体' in w for w in doc.warnings)  # Mainland warnings unchanged.
