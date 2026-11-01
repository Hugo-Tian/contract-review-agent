"""Search a bounded official-source reference library, without model-written law."""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

from .profiles import current, cn
from . import hk_legal

# One cached corpus per region. CORPUS/SOURCES keep their mainland meaning for existing callers.
CORPUS = Path(__file__).with_name('legal_corpus.json')
HK_CORPUS = Path(__file__).with_name('legal_corpus_hk.json')
SOURCES = cn.LEGAL_SOURCES


def corpus_path(region=None):
    # Looked up at call time so tests can monkeypatch CORPUS / HK_CORPUS.
    return {'cn': CORPUS, 'hk': HK_CORPUS}[region or current().region]


refresh_lock = asyncio.Lock()


def extract_articles(html, source):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav']):
        tag.decompose()
    text = soup.get_text('\n', strip=True)
    starts = list(re.finditer(r'(?m)^\s*(第[一二三四五六七八九十百千零〇]+条)\s*', text))
    found = {}
    for i, match in enumerate(starts):
        number = match.group(1)
        if number in source['articles']:
            end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
            content = text[match.end():end].strip()
            # Chapter headings belong to the next article, not this one.
            content = re.split(r'\n第[一二三四五六七八九十]+[章节编分]', content)[0].strip()
            if 8 < len(content) < 6000:
                found[number] = {'id': source['id'] + ':' + number, 'article': number, 'text': content,
                                 **{k: source[k] for k in ('title', 'url', 'effective', 'edition')}}
    missing = set(source['articles']) - set(found)
    if missing:
        raise ValueError('官方页面结构发生变化，未更新该来源。')
    return list(found.values())


def load():
    path = corpus_path()
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'articles': [], 'sources': [], 'updated': None}


async def refresh():
    profile = current()
    if not profile.legal['sources']:
        return {'sources': [], 'updated': None, 'count': 0, 'error': profile.legal['note']}
    if profile.legal.get('local_pdf'):
        async with refresh_lock:
            return await asyncio.to_thread(refresh_local, profile)
    async with refresh_lock:
        previous = load()
        target = corpus_path(profile.region)
        now = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client:
            async def fetch(source):
                try:
                    response = await client.get(source['url'], headers={'User-Agent': 'ContractReader/1.0'})
                    response.raise_for_status()
                    # These official pages declare UTF-8. Decode explicitly when header is absent.
                    response.encoding = 'utf-8'
                    rows = extract_articles(response.text, source)
                    return source, [{**r, 'retrieved': now} for r in rows], None
                except (httpx.HTTPError, ValueError):
                    rows = [r for r in previous['articles'] if r['id'].startswith(source['id'] + ':')]
                    return source, rows, '连接失败或页面结构变化，保留已有缓存；请打开官方来源核对。'
            results = await asyncio.gather(*(fetch(s) for s in profile.legal['sources']))
        articles, sources = [], []
        for source, rows, error in results:
            articles.extend(rows)
            sources.append({'title': source['title'], 'url': source['url'], 'count': len(rows), 'error': error})
        corpus = {'articles': articles, 'sources': sources, 'updated': now}
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(target)
        return {'sources': sources, 'updated': now, 'count': len(articles)}


SOURCE_DIR_ENV = 'HK_LEGAL_SOURCE_DIR'


def refresh_local(profile):
    """Rebuild a region's library from official PDFs in HK_LEGAL_SOURCE_DIR.

    A chapter that cannot be read keeps its cached rows and reports why. If nothing could be read,
    the cache file is left untouched.
    """
    previous = load()
    folder = os.getenv(SOURCE_DIR_ENV, '')
    now = datetime.now(timezone.utc).isoformat()
    articles, sources, refreshed = [], [], 0
    for source in profile.legal['sources']:
        kept = [r for r in previous['articles'] if r['id'].startswith(source['id'] + ':')]
        old = next((s for s in previous['sources'] if s.get('id') == source['id']), {})
        try:
            files = sorted(Path(folder).glob(source['file'] + '*.pdf')) if folder else []
            if len(files) != 1:
                raise FileNotFoundError(source['file'])
            effective, chapter, rows = hk_legal.extract(files[0], source)
            retrieved = datetime.fromtimestamp(files[0].stat().st_mtime, timezone.utc).isoformat()
            rows = [hk_row(source, chapter, effective, retrieved, files[0].name, r) for r in rows]
            sources.append({'id': source['id'], 'title': chapter['zh'], 'title_en': chapter['en'], 'url': source['url'],
                            'effective': effective, 'count': len(rows), 'error': None})
            refreshed += 1
        except FileNotFoundError:
            rows = kept
            sources.append({**old, 'id': source['id'], 'url': source['url'], 'count': len(rows),
                            'error': f'未在 {SOURCE_DIR_ENV} 指定的文件夹中找到唯一的“{source["file"]}…pdf”，保留已有缓存。'})
        except (OSError, ValueError, RuntimeError, StopIteration):
            rows = kept
            sources.append({**old, 'id': source['id'], 'url': source['url'], 'count': len(rows),
                            'error': '官方 PDF 无法读取或版式变化，保留已有缓存；请打开官方来源核对。'})
        articles.extend(rows)
    if refreshed:
        target = corpus_path(profile.region)
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps({'articles': articles, 'sources': sources, 'updated': now}, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(target)
    return {'sources': sources, 'updated': now if refreshed else previous.get('updated'), 'count': len(articles)}


def hk_row(source, chapter, effective, retrieved, filename, r):
    if r['schedule'] and not r['heading_zh']:
        r = {**r, 'heading_zh': source['schedule_titles'][r['schedule']][0], 'heading_en': source['schedule_titles'][r['schedule']][1]}
    if r['schedule']:
        key, article, article_en = f"S{r['schedule']}-{r['number']}", f"附表{r['schedule']}第{r['number']}條", f"Schedule {r['schedule']}, section {r['number']}"
    else:
        key, article, article_en = r['number'], f"第{r['number']}條", f"s. {r['number']}"
    return {'id': f"{source['id']}:{key}", 'article': article, 'article_en': article_en,
            'heading': r['heading_zh'], 'heading_en': r['heading_en'], 'text': r['text_zh'], 'text_en': r['text_en'],
            'title': chapter['zh'], 'title_en': chapter['en'], 'url': source['url'], 'effective': effective,
            'edition': '電子版香港法例整章綜合版本（經核證文本）', 'retrieved': retrieved,
            'obtained': '用户从电子版香港法例下载的官方 PDF：' + filename, 'scope': source['scope']}


def search(query):
    profile = current()
    data = load()
    q = query.strip()
    aliases = profile.legal['aliases']
    terms = set(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+', q))
    for key, values in aliases.items():
        if key in q:
            terms.update(values)
    variants = [q]
    if profile.legal.get('to_traditional'):
        # Users type Simplified Chinese; Hong Kong statutes are in Traditional Chinese and English.
        variants.append(q.translate(profile.legal['to_traditional']))
        terms.update(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+', variants[1]))
    if len(q) > 2:
        for v in variants:
            pairs = (v[i:i+2] for i in range(len(v)-1) if not v[i:i+2].isspace())
            # Two-letter English fragments ("de", "po") match almost everything; only Chinese pairs help.
            terms.update(p for p in pairs if len(variants) == 1 or re.fullmatch(r'[一-鿿]{2}', p))
    ranked = []
    for article in data['articles']:
        text = article['article'] + article['title'] + article['text']
        if 'text_en' in article:
            text = (text + article['heading'] + article['heading_en'] + article['title_en'] + article['text_en']).lower()
        score = sum(min(text.count(t.lower() if 'text_en' in article else t), 5) * (3 if len(t) > 2 else 1) for t in terms)
        if score:
            ranked.append((score, article))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return {'query': q, 'results': [r for _, r in ranked[:15]], 'total_matches': len(ranked), 'count': len(data['articles']), 'sources': data['sources'],
            'note': profile.legal['note']}
