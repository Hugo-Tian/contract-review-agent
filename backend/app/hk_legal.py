"""Extract selected sections from bilingual eLegislation "Consolidated version" PDFs.

Each PDF page is a two-page spread: Chinese on the left half, English on the right. Running
headers and footers sit at fixed heights. A section starts with a block whose first line is its
number ("120AAZC."), followed by its heading on the same or the next line. Headings come from
the chapter's own contents pages. Text is copied verbatim; nothing is written or paraphrased.
"""
import re
from pathlib import Path
import pymupdf

TOP, BOTTOM = 100, 555          # page-furniture bands (points) on the 842 x 595 spread
NUMBER = re.compile(r'^(\d+[A-Z]*(?:-\d+[A-Z]*)?)\.(?:\s+(.*))?$')
SCHEDULE = re.compile(r'^(?:(?:First|Second|Third|Fourth|Fifth) Schedule|Schedule(?:\s*\d+[A-Z]?)?|附表\s*\d*[A-Z]?)$')
HAN = r'一-鿿，、；：。（）「」《》—'


def version_date(doc):
    match = re.search(r'Version date\s*\n\s*(\d{1,2}\.\d{1,2}\.\d{4})', doc[0].get_text())
    if not match:
        raise ValueError('找不到版本日期，文件可能不是电子版法例导出的综合版本。')
    day, month, year = match.group(1).split('.')
    return f'{year}-{int(month):02}-{int(day):02}'


def chapter_title(doc):
    """Short titles as printed on the cover, e.g. 業主與租客( 綜合) 條例 / Landlord and Tenant (Consolidation) Ordinance."""
    lines = [l.strip() for l in doc[0].get_text().split('\n') if l.strip()]
    zh = next(l for l in lines if l.startswith('《')).strip('《》')
    en = next(l for l in lines if re.search(r'(Ordinance|Regulation)$', l))
    return {'zh': zh, 'en': en}


def join(lines):
    """Join wrapped lines: no space inside Chinese text, one space inside English text."""
    text = ''
    for line in (l.strip() for l in lines):
        if not line:
            continue
        if text and not (re.search(f'[{HAN}]$', text) and re.match(f'[{HAN}]', line)):
            text += ' '
        text += line
    return text


def contents(doc):
    """{number: {'zh': heading, 'en': heading}} from the contents pages (marked T-n)."""
    rows = {}
    for page in doc:
        if not re.search(r'\bT-\d+\b', page.get_text()):
            continue
        mid = page.rect.width / 2
        for b in page.get_text('blocks'):
            lines = [l.strip() for l in b[4].split('\n') if l.strip()]
            match = NUMBER.match(lines[0]) if lines else None
            if not match:
                continue
            parts = ([match.group(2)] if match.group(2) else []) + lines[1:]
            title = join(p for p in parts if not re.fullmatch(r'[A-Z]?\d+[A-Z]?-\d+', p))
            title = re.sub(r'\s+\d{1,3}$', '', title)  # some chapters print the page number after the title
            rows.setdefault(match.group(1), {})['en' if b[0] >= mid - 5 else 'zh'] = title
    return rows


def streams(doc):
    """Body blocks per language in reading order, as (lines, is_cross_heading)."""
    sides = {'zh': [], 'en': []}
    for page in doc:
        if page.number < 2 or re.search(r'\bT-\d+\b', page.get_text()):
            continue
        mid = page.rect.width / 2
        blocks = [b for b in page.get_text('blocks') if TOP <= b[1] <= BOTTOM]
        for side, (left, right) in (('zh', (0, mid)), ('en', (mid, page.rect.width))):
            own = sorted((b for b in blocks if left - 5 <= b[0] < right - 5), key=lambda b: (round(b[1]), b[0]))
            if not own:
                continue
            column = max(b[2] for b in own) - min(b[0] for b in own)
            centre = (min(b[0] for b in own) + max(b[2] for b in own)) / 2
            for b in own:
                lines = [l.strip() for l in b[4].split('\n') if l.strip()]
                if not lines:
                    continue
                # Cross-headings ("Subdivision 1—General Provisions", "General", "在佣金方面的爭議等") are short,
                # centred on the text column, not numbered and not ending a clause.
                flat = join(lines)
                heading = (abs((b[0] + b[2]) / 2 - centre) < 30 and b[2] - b[0] < 0.75 * column and len(lines) <= 2 and not re.match(r'[(（\d]', flat)
                           and not re.search(r'[;:,。；：，]$', flat) and not flat[:1].islower())
                sides[side].append((lines, heading))
    return sides


def sections(blocks, titles, lang):
    """{number: text} for every section before the schedules; headings removed from the text."""
    found, current, body, matched = {}, None, [], False

    def close():
        if current and current not in found:
            found[current] = (clean(body), matched)

    for lines, heading in blocks:
        if heading:
            # Only a heading can start the schedules; body text may begin with "附表7 的條文…".
            if SCHEDULE.match(lines[0]) and current:
                break
            continue
        match = NUMBER.match(lines[0])
        if match and match.group(1) in titles and lang in titles[match.group(1)]:
            close()
            current = match.group(1)
            rest = ([match.group(2)] if match.group(2) else []) + lines[1:]
            first, matched = strip_heading(rest, titles[current][lang])
            body = [first]
            continue
        if current:
            body.append(join(lines))
    close()
    return found


def strip_heading(lines, title):
    """Drop the heading (possibly wrapped over several lines) from the start of a section."""
    want = re.sub(r'\s+', '', title)
    taken, consumed = '', 0
    for line in lines:
        if want.startswith(taken + re.sub(r'\s+', '', line)) and taken != want:
            taken += re.sub(r'\s+', '', line)
            consumed += 1
        else:
            break
    # A mismatch (e.g. repealed sections) is recorded rather than raised; extract() rejects it for selected sections.
    return join(lines[consumed:]), taken == want


def clean(parts):
    text = '\n'.join(p for p in parts if p)
    # Paragraph markers stand alone in the PDF ("(1)", "(a)"); keep each on the line with its text.
    text = re.sub(r'(^|\n)(\(\w+\))\n', r'\1\2 ', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


def schedule_paragraphs(blocks, title):
    """{number: (heading or '', text)} for the numbered paragraphs of one schedule.

    A paragraph starts with "2. Stamp duty borne by landlord" (a titled paragraph) or
    "1. Sections 7, 8 and 9 do not apply to—" (no title; the line is part of the text).
    """
    found, current, heading, body, inside = {}, None, '', [], False
    for lines, is_heading in blocks:
        flat = join(lines)
        if not inside:
            inside = flat == title  # a whole line reading exactly "Schedule 7" / "附表7"
            continue
        if SCHEDULE.match(flat):
            break
        if is_heading:
            continue
        match = NUMBER.match(lines[0])
        if match and (match.group(2) or len(lines) > 1):
            if current and current not in found:
                found[current] = (heading, clean(body))
            current = match.group(1)
            rest = ([match.group(2)] if match.group(2) else []) + lines[1:]
            first = rest[0]
            titled = len(rest) == 1 and len(first) < 70 and not re.search(r'[—.,;:。，；：]$', first)
            heading, body = (first, []) if titled else ('', [join(rest)])
            continue
        if current:
            body.append(flat)
    if current and current not in found:
        found[current] = (heading, clean(body))
    return found


ROW = re.compile(r'^\((?:[a-z]|i|ii|iii|iv|v|vi)\)')


def table_head(doc, start, stop, split, after=None):
    """Verbatim rows of one head of a two-column schedule table, e.g. Cap. 117 First Schedule head 1(2).

    `split` is the x position dividing "nature of instrument" from "stamp duty / time / persons liable"
    on this language's half of the spread. Each row starts at a left-column item such as "(a)" or "(iii)";
    right-column cells are attached to the row they sit beside. The column headers repeated on every page
    are dropped; the text of every cell is kept as printed.
    """
    rows, current, started, begun = [], None, False, after is None
    for page in doc:
        text = page.get_text()
        if not begun:
            begun = after in text
            if not begun:
                continue
        mid = page.rect.width / 2
        left_half = split < mid
        blocks = [b for b in page.get_text('blocks') if TOP + 52 <= b[1] <= BOTTOM and (b[0] < mid - 5) == left_half]
        for b in sorted(blocks, key=lambda b: (round(b[1]), b[0])):
            lines = [l.strip() for l in b[4].split('\n') if l.strip()]
            if not lines:
                continue
            flat = join(lines)
            if not started:
                started = flat == start
                continue
            if flat.startswith(stop):
                return [join(r['nature']) + (' —— ' + join(r['duty']) if r['duty'] else '') for r in rows]
            if b[0] < split:
                # Each item, and the cross-reference line after the last one, starts a new row.
                if ROW.match(flat) or flat.startswith(('另見', 'And see')) or current is None:
                    current = {'nature': [flat], 'duty': []}
                    rows.append(current)
                else:
                    current['nature'].append(flat)
            elif current is not None:
                current['duty'].append(flat)
    raise ValueError(f'未找到表格段落 {start!r} 的结尾 {stop!r}。')


def extract(path: Path, source):
    """(version date, {'zh', 'en'} chapter title, rows) for one chapter; raises if any requested provision is missing.

    Rows are {'number', 'schedule', 'heading_zh', 'heading_en', 'text_zh', 'text_en'}; `schedule` is
    None for a section of the body, or the schedule number for a schedule paragraph.
    """
    with pymupdf.open(path) as doc:
        effective = version_date(doc)
        chapter = chapter_title(doc)
        titles = contents(doc)
        sides = streams(doc)
    zh, en = sections(sides['zh'], titles, 'zh'), sections(sides['en'], titles, 'en')
    rows = []
    for number in source['articles']:
        if number not in zh or number not in en:
            raise ValueError(f'{source["id"]} 第 {number} 条未能同时取得中英文本。')
        (text_zh, ok_zh), (text_en, ok_en) = zh[number], en[number]
        if not (ok_zh and ok_en):
            raise ValueError(f'{source["id"]} 第 {number} 条的标题与目录不一致，可能解析错位。')
        rows.append(checked(source, number, None, titles[number]['zh'], titles[number]['en'], text_zh, text_en))
    for schedule, numbers in source.get('schedules', {}).items():
        zh_paras = schedule_paragraphs(sides['zh'], f'附表{schedule}')
        en_paras = schedule_paragraphs(sides['en'], f'Schedule {schedule}')
        for number in numbers:
            if number not in zh_paras or number not in en_paras:
                raise ValueError(f'{source["id"]} 附表{schedule} 第 {number} 段未能同时取得中英文本。')
            (heading_zh, text_zh), (heading_en, text_en) = zh_paras[number], en_paras[number]
            rows.append(checked(source, number, schedule, heading_zh, heading_en, text_zh, text_en))
    for table in source.get('tables', []):
        with pymupdf.open(path) as doc:
            text_zh = '\n'.join([table['columns'][0]] + table_head(doc, *table['zh']))
            text_en = '\n'.join([table['columns'][1]] + table_head(doc, *table['en']))
        row = checked(source, table['key'], None, table['heading'][0], table['heading'][1], text_zh, text_en)
        rows.append({**row, 'article_zh': table['article'][0], 'article_en': table['article'][1]})
    return effective, chapter, rows


def checked(source, number, schedule, heading_zh, heading_en, text_zh, text_en):
    where = f'附表{schedule} 第 {number} 段' if schedule else f'第 {number} 条'
    if len(text_zh) < 10 or len(text_en) < 20:
        raise ValueError(f'{source["id"]} {where}文本过短，可能解析失败。')
    return {'number': number, 'schedule': schedule, 'heading_zh': heading_zh, 'heading_en': heading_en,
            'text_zh': text_zh, 'text_en': text_en}
