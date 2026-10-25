"""Search a bounded official-source reference library, without model-written law."""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

CORPUS = Path(__file__).with_name('legal_corpus.json')
SOURCES = [
    {'id': 'civil', 'title': '中华人民共和国民法典', 'url': 'https://www.cac.gov.cn/2020-06/01/c_15925617772683192.htm', 'effective': '2021-01-01', 'edition': '2020年公布版本', 'articles': ['第四百六十五条', '第四百六十六条', '第四百六十九条', '第四百七十三条', '第四百九十六条', '第四百九十七条', '第四百九十八条', '第五百零六条', '第五百零九条', '第五百一十条', '第五百四十三条', '第五百六十二条', '第五百六十三条', '第五百六十五条', '第五百六十六条', '第五百七十七条', '第五百八十四条', '第五百八十五条']},
    {'id': 'consumer', 'title': '中华人民共和国消费者权益保护法', 'url': 'https://www.samr.gov.cn/zfjcj/tzgg/art/2023/art_615af9ed6bcd4974bf853dd2e02bc663.html', 'effective': '2014-03-15', 'edition': '2013年修正版本', 'articles': ['第二条', '第八条', '第九条', '第十条', '第二十条', '第二十六条', '第三十九条', '第五十三条']},
    {'id': 'regulation', 'title': '中华人民共和国消费者权益保护法实施条例', 'url': 'https://www.mee.gov.cn/zcwj/gwywj/202403/t20240320_1068830.shtml', 'effective': '2024-07-01', 'edition': '国务院令第778号', 'articles': ['第九条', '第十二条', '第十七条', '第二十二条']},
    {'id': 'prepaid', 'title': '最高人民法院关于审理预付式消费民事纠纷案件适用法律若干问题的解释', 'url': 'https://www.court.gov.cn/zixun/xiangqing/459321.html', 'effective': '2025-05-01', 'edition': '法释〔2025〕4号', 'articles': ['第一条', '第五条', '第六条', '第八条', '第十二条', '第十三条', '第十四条', '第十五条', '第十六条', '第十七条', '第十八条', '第十九条', '第二十条', '第二十一条', '第二十二条', '第二十五条']},
]
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
    if CORPUS.exists():
        return json.loads(CORPUS.read_text(encoding='utf-8'))
    return {'articles': [], 'sources': [], 'updated': None}


async def refresh():
    async with refresh_lock:
        previous = load()
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
            results = await asyncio.gather(*(fetch(s) for s in SOURCES))
        articles, sources = [], []
        for source, rows, error in results:
            articles.extend(rows)
            sources.append({'title': source['title'], 'url': source['url'], 'count': len(rows), 'error': error})
        corpus = {'articles': articles, 'sources': sources, 'updated': now}
        temp = CORPUS.with_suffix('.tmp')
        temp.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(CORPUS)
        return {'sources': sources, 'updated': now, 'count': len(articles)}


def search(query):
    data = load()
    q = query.strip()
    aliases = {'退款': ['退还', '返还', '预付款', '解除'], '退费': ['退还', '返还', '预付款'], '销售': ['承诺', '宣传', '广告'], '口头': ['口头', '承诺'], '霸王': ['格式条款'], '违约金': ['违约金', '损失'], '课程': ['培训', '服务'], '承诺': ['承诺', '宣传', '合同内容']}
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
            'note': '检索范围为4部官方法律法规及司法解释中的合同、预付消费相关条文选编，不是全国法规库。网页获取成功不等于已确认现行有效；请核对版本及适用时间。结果是原文参考，不自动判断本合同适用哪条法律。'}
