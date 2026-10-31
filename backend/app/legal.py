"""Search a bounded official-source reference library, without model-written law."""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

from .profiles import current, cn

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


def search(query):
    profile = current()
    data = load()
    q = query.strip()
    aliases = profile.legal['aliases']
    terms = set(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+', q))
    for key, values in aliases.items():
        if key in q:
            terms.update(values)
    if len(q) > 2:
        terms.update(q[i:i+2] for i in range(len(q)-1) if not q[i:i+2].isspace())
    ranked = []
    for article in data['articles']:
        text = article['article'] + article['title'] + article['text']
        score = sum(min(text.count(t), 5) * (3 if len(t) > 2 else 1) for t in terms)
        if score:
            ranked.append((score, article))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return {'query': q, 'results': [r for _, r in ranked[:15]], 'total_matches': len(ranked), 'count': len(data['articles']), 'sources': data['sources'],
            'note': profile.legal['note']}
