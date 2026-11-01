"""Hong Kong statute library: verbatim extraction from e-Legislation PDFs, cache fallback, bilingual search."""
import asyncio
import json
import os
import shutil
from pathlib import Path
import pytest
from app import hk_legal, legal
from app.profiles import hk

ROOT = Path(__file__).resolve().parents[2]
# The official PDFs are not committed; tests that re-extract from them run only where they are present.
PDF_DIR = Path(os.getenv('HK_LEGAL_SOURCE_DIR', 'C:/Users/omen/Desktop/所需条例'))
needs_pdfs = pytest.mark.skipif(not any(PDF_DIR.glob('Cap 7 *.pdf')), reason='official e-Legislation PDFs not available')
VERSIONS = {'cap7': '2024-04-19', 'cap511': '2025-08-24', 'cap511C': '2024-11-14', 'cap117': '2026-02-26', 'cap71': '2018-12-13'}


@pytest.fixture(autouse=True)
def hong_kong(monkeypatch):
    monkeypatch.setenv('REGION', 'hk')


def corpus():
    return json.loads(legal.HK_CORPUS.read_text(encoding='utf-8'))


def test_corpus_has_every_selected_provision_with_source_metadata():
    data = corpus()
    expected = sum(len(s['articles']) + sum(len(v) for v in s.get('schedules', {}).values()) for s in hk.LEGAL_SOURCES)
    rows = data['articles']
    assert len(rows) == expected == 40 and len({r['id'] for r in rows}) == 40
    for r in rows:
        source = r['id'].split(':')[0]
        assert r['url'] == f'https://www.elegislation.gov.hk/hk/{source}'
        assert r['effective'] == VERSIONS[source] and r['retrieved'] and '下载的官方 PDF' in r['obtained']
        assert r['text'] and r['text_en'] and r['heading'] and r['heading_en'] and r['scope']
        for field in ('text', 'text_en'):
            assert not any(token in r[field] for token in ('Verified Copy', '經核證文本', 'Last updated date', '最後更新日期'))
    assert all(s['error'] is None for s in data['sources'])


def test_key_provisions_are_verbatim_in_both_languages():
    rows = {r['id']: r for r in corpus()['articles']}
    deposit = rows['cap7:120AAZC']
    assert deposit['article'] == '第120AAZC條' and deposit['heading'] == '租金按金' and deposit['heading_en'] == 'Rental deposit'
    assert '不得超過在租賃下的2 個月租金' in deposit['text']
    assert 'may not be more than 2 months’ rent' in deposit['text_en'] and 'whichever is the later.' in deposit['text_en']
    stamp = rows['cap7:S7-2']
    assert stamp['article'] == '附表7第2條' and stamp['text'] == '就屬規管租賃的租賃協議徵收的印花稅，須由業主單獨承擔。'
    assert rows['cap71:S1-1']['heading_en'] == 'Scope of Sections 7, 8, 9 and 12'
    assert 'creation or transfer of an interest in land' in rows['cap71:S1-1']['text_en']
    assert 'Disputes as regards Commission' not in rows['cap511:48']['text_en']   # cross-heading not swallowed


@pytest.mark.parametrize('query,first', [('按金', 'cap7:120AAZC'), ('提前退租', 'cap7:120AAZH'), ('印花税', 'cap117:4'), ('deposit', 'cap7:120AAZC')])
def test_rental_terms_find_provisions_in_simplified_or_english(query, first):
    result = legal.search(query)
    assert result['results'][0]['id'] == first
    assert result['total_matches'] < 15  # English letter pairs no longer match everything


def test_parser_helpers():
    assert hk_legal.join(['租客應繳付的租', '金按金']) == '租客應繳付的租金按金'
    assert hk_legal.join(['the rental deposit', 'payable']) == 'the rental deposit payable'
    assert hk_legal.NUMBER.match('120AAZC.').group(1) == '120AAZC'
    assert hk_legal.NUMBER.match('119L.\t Endorsement of tenancy agreement').group(2) == 'Endorsement of tenancy agreement'
    assert hk_legal.SCHEDULE.match('Schedule 7') and hk_legal.SCHEDULE.match('附表7') and hk_legal.SCHEDULE.match('Schedule')
    assert not hk_legal.SCHEDULE.match('Schedule)') and not hk_legal.SCHEDULE.match('附表7 的條文')
    assert hk_legal.strip_heading(['Rental deposit', '(1) text'], 'Rental deposit') == ('(1) text', True)
    assert hk_legal.strip_heading(['(Repealed 3 of 2004)'], '(Repealed)')[1] is False


def test_refresh_without_source_folder_keeps_cache(monkeypatch, tmp_path):
    target = tmp_path / 'hk.json'
    shutil.copyfile(legal.HK_CORPUS, target)
    before = target.read_bytes()
    monkeypatch.setattr(legal, 'HK_CORPUS', target)
    monkeypatch.delenv('HK_LEGAL_SOURCE_DIR', raising=False)
    result = asyncio.run(legal.refresh())
    assert result['count'] == 40 and all('保留已有缓存' in s['error'] for s in result['sources'])
    assert target.read_bytes() == before


@needs_pdfs
def test_extraction_is_reproducible_from_official_pdfs():
    rows = {r['id']: r for r in corpus()['articles']}
    for source in hk.LEGAL_SOURCES:
        path = next(PDF_DIR.glob(source['file'] + '*.pdf'))
        effective, chapter, extracted = hk_legal.extract(path, source)
        assert effective == VERSIONS[source['id']] and chapter['en'].endswith(('Ordinance', 'Regulation'))
        for r in extracted:
            key = f"S{r['schedule']}-{r['number']}" if r['schedule'] else r['number']
            cached = rows[f"{source['id']}:{key}"]
            assert (cached['text'], cached['text_en']) == (r['text_zh'], r['text_en'])


@needs_pdfs
def test_refresh_with_one_broken_pdf_keeps_that_chapter_from_cache(monkeypatch, tmp_path):
    folder = tmp_path / 'pdfs'
    folder.mkdir()
    shutil.copyfile(next(PDF_DIR.glob('Cap 71 *.pdf')), folder / 'Cap 71 Consolidated version (test).pdf')
    (folder / 'Cap 7 Consolidated version (broken).pdf').write_bytes(b'%PDF-1.4 not really a pdf')
    target = tmp_path / 'hk.json'
    shutil.copyfile(legal.HK_CORPUS, target)
    monkeypatch.setattr(legal, 'HK_CORPUS', target)
    monkeypatch.setenv('HK_LEGAL_SOURCE_DIR', str(folder))
    result = asyncio.run(legal.refresh())
    status = {s['id']: s for s in result['sources']}
    assert status['cap71']['error'] is None and status['cap71']['count'] == 1
    assert '无法读取' in status['cap7']['error'] and status['cap7']['count'] == 22
    assert '找不到' in status['cap511']['error'] or '未在' in status['cap511']['error']
    assert result['count'] == 40
    assert len(json.loads(target.read_text(encoding='utf-8'))['articles']) == 40
