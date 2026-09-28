"""Read the five published Google Sites pages without browser/runtime packages.

The Google Sites HTML is data, never executable input. Missing page identities or
section boundaries raise ParseError so the caller can keep its last good copy.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

SOURCE_BASE = 'https://sites.google.com/view/guoleizhongshomepage/'
PAGES = ('home', 'research', 'talks', 'teaching', 'links')
VOID_TAGS = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
IGNORED_TAGS = frozenset(('script', 'style', 'template', 'noscript', 'nav'))
BLOCK_TAGS = frozenset(('p', 'li', 'h1', 'h2', 'h3', 'h4', 'small', 'figcaption'))


class ParseError(ValueError):
    """Published source does not match the supported page structure."""


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\u200b', '')).strip()


def safe_url(value: str | None) -> str | None:
    """Keep ordinary absolute web/mail links; never copy executable schemes."""
    if not value:
        return None
    value = value.strip()
    if re.search(r'[\x00-\x20\x7f<>\\]', value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in ('http', 'https'):
            if not parsed.hostname or parsed.username or parsed.password:
                return None
            parsed.port  # Invalid ports must not survive URL validation.
            return value
        if parsed.scheme.lower() == 'mailto' and re.fullmatch(r'[^?@]+@[^?@]+', parsed.path):
            if not re.search(r'%0[ad]', value, re.I):
                return value
    except ValueError:
        pass
    return None


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('document')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def visible(node: Node) -> bool:
    return node.tag not in IGNORED_TAGS and 'hidden' not in node.attrs and node.attrs.get('aria-hidden') != 'true'


def item(node: Node) -> dict:
    """Flatten inline markup and record exact anchor offsets in the clean text."""
    parts: list[str] = []
    anchors: list[tuple[int, int, str]] = []
    length = 0

    def walk(current: Node):
        nonlocal length
        if not visible(current):
            return
        start = length
        for child in current.children:
            if isinstance(child, str):
                value = child.replace('\u200b', '')
                parts.append(value)
                length += len(value)
            elif child.tag == 'br':
                parts.append(' ')
                length += 1
            else:
                walk(child)
                if child.tag in BLOCK_TAGS:
                    parts.append(' ')
                    length += 1
        href = safe_url(current.attrs.get('href')) if current.tag == 'a' else None
        if href:
            anchors.append((start, length, href))

    walk(node)
    raw = ''.join(parts)
    text = clean(raw)
    links = []
    for start, end, href in sorted(anchors):
        label = clean(raw[start:end])
        if not label:
            continue
        leading = len(raw[start:end]) - len(raw[start:end].lstrip())
        offset = len(re.sub(r'\s+', ' ', raw[:start + leading]).lstrip())
        if text[offset:offset + len(label)] != label:
            raise ParseError('Could not map a source link onto its visible label')
        links.append({'label': label, 'url': href, 'start': offset, 'end': offset + len(label)})
    return {'text': text, 'links': links}


def text_of(node: Node) -> str:
    return item(node)['text']


def blocks(root: Node) -> list[Node]:
    """Top-level text blocks, without duplicate paragraphs inside list items."""
    result = []

    def walk(node: Node):
        if not visible(node):
            return
        if node.tag in BLOCK_TAGS:
            if text_of(node):
                result.append(node)
            return
        for child in node.children:
            if isinstance(child, Node):
                walk(child)
    walk(root)
    return result


def document(html: str, page: str) -> tuple[Node, Node, list[Node]]:
    parser = DocumentParser()
    parser.feed(html)
    parser.close()
    nodes = list(parser.root.nodes())
    title = next((text_of(n) for n in nodes if n.tag == 'title'), '')
    expected = 'Guolei ZHONG' + ('' if page == 'home' else ' - ' + page.title())
    if clean(title).casefold() != expected.casefold():
        raise ParseError(f'{page}: missing or unexpected published page title')
    mains = [n for n in nodes if n.tag == 'main' or n.attrs.get('role') == 'main']
    if len(mains) != 1:
        raise ParseError(f'{page}: expected one main landmark')
    main = mains[0]
    # Google Sites places role=main on its header, not the body container.
    # All published sections share the header section's immediate parent.
    header_section = next((n for n in main.ancestors() if n.tag == 'section'), None)
    root = header_section.parent if header_section is not None else main
    if root is None:
        raise ParseError(f'{page}: missing content container')
    headings = [text_of(n) for n in main.nodes() if n.tag == 'h1']
    if page == 'home':
        identity = any('guolei zhong' in h.casefold() for h in headings)
    else:
        identity = any(h.casefold() == page for h in headings)
    if not identity:
        raise ParseError(f'{page}: missing page heading')
    return parser.root, root, blocks(root)


def heading_key(value: str) -> str:
    return clean(value).rstrip(':').casefold()


def ensure_items(items: list, context: str) -> None:
    if not items:
        raise ParseError(f'{context}: no content found; refusing to replace the last good copy')


def home_data(root: Node, page_blocks: list[Node], previous: dict) -> dict:
    about = next((i for i, n in enumerate(page_blocks) if heading_key(text_of(n)) == 'about me'), None)
    if about is None:
        raise ParseError('home: missing About me section')
    about_items = []
    for node in page_blocks[about + 1:]:
        if node.tag == 'li':
            about_items.append(item(node))
        elif node.tag.startswith('h'):
            break
    ensure_items(about_items, 'home/About me')
    profile = deepcopy(previous.get('profile', {}))
    profile.setdefault('name', 'Guolei Zhong')
    profile.setdefault('displayName', 'Guolei ZHONG')
    profile.setdefault('chineseName', '仲国磊')
    cv = next((link['url'] for row in about_items for link in row['links'] if link['label'].casefold() in ('cv', 'curriculum vitae')), None)
    if not cv:
        raise ParseError('home: missing public CV link')
    profile['cv'] = cv
    bio, emails, institutions = [], [], []
    profile['phone'] = ''
    profile['address'] = ''
    for row in about_items:
        value = row['text']
        key = value.casefold()
        if key.startswith(('email:', 'e-mail:')):
            email_text = re.sub(r'\[at\]', '@', value, flags=re.I)
            emails += re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', email_text)
        elif key.startswith(('phone:', 'telephone:')):
            profile['phone'] = value.split(':', 1)[1].strip()
        elif key.startswith(('current address:', 'address:')):
            profile['address'] = value.split(':', 1)[1].strip()
        else:
            bio.append(value)
            institutions.extend(link for link in row['links'] if link['url'] != cv)
    if not emails or not bio:
        raise ParseError('home: missing biography or email contact')
    profile['bio'] = bio
    profile['emails'] = list(dict.fromkeys(emails))
    profile['institutionLinks'] = institutions
    # These legacy summary fields cannot reliably be inferred from free prose.
    # Dynamic rendering uses the complete source bio, so do not retain old facts.
    for key in ('position', 'institution', 'school', 'since', 'researchInterest', 'portraitWidth', 'portraitHeight'):
        profile.pop(key, None)
    images = [n for n in root.nodes() if n.tag == 'img' and visible(n)]
    portrait = next((safe_url(n.attrs.get('src')) for n in images if safe_url(n.attrs.get('src'))), None)
    captions = [text_of(n) for n in page_blocks if n.tag in ('small', 'figcaption')]
    if not portrait or not captions:
        raise ParseError('home: missing portrait or photo caption')
    profile['portrait'] = portrait
    profile['portraitCredit'] = captions[-1]
    return {'profile': profile, 'homeItems': about_items, 'homeHeading': text_of(page_blocks[about])}


def publication(row: dict, order: int, category: str) -> dict:
    source = row['text']
    authors = re.match(r'^\(with (.*?)\)\s*(.*)', source)
    coauthors, remainder = (authors[1], authors[2]) if authors else ('', source)
    title, sep, citation = remainder.partition(', ')
    appendix = None
    if ' (with an appendix by ' in title:
        title, appendix = title.split(' (with an appendix by ', 1)
        appendix = appendix.rstrip(')')
    citation = re.sub(r'\s*\[[^]]+\]', '', citation).strip() if sep else ''
    year = re.search(r'\b((?:19|20)\d{2})\b', citation)
    return {'id': f'paper-{order:02d}', 'sourceOrder': order, 'title': title,
            'coauthors': coauthors, 'appendixBy': appendix, 'citation': citation,
            'year': int(year[1]) if year else None,
            'status': 'preprint' if category == 'preprints' else ('accepted' if 'to appear' in source.casefold() else 'published'),
            'links': row['links'], 'sourceText': source}


def research_data(page_blocks: list[Node]) -> dict:
    sections: dict[str, list[dict]] = {}
    headings = {}
    current = None
    for node in page_blocks:
        row = item(node)
        key = heading_key(row['text'])
        section = None
        if node.tag != 'li':
            if re.fullmatch(r'about my research interests?', key):
                section = 'intro'
            elif re.fullmatch(r'publications?(?: \(including accepted papers\))?', key):
                section = 'publications'
            elif key == 'preprints':
                section = 'preprints'
            elif key in ('other texts & notes', 'other texts and notes'):
                section = 'notes'
        if section:
            if section in sections:
                raise ParseError(f'research: duplicate {section} section')
            current = section
            sections[current] = []
            headings[current] = row['text']
        elif current and (node.tag == 'li' or current == 'intro'):
            sections[current].append(row)
    for key in ('intro', 'publications', 'preprints', 'notes'):
        if key not in sections:
            raise ParseError(f'research: missing {key} section')
        if key in ('intro', 'publications'):
            ensure_items(sections[key], f'research/{key}')
    profiles, intro = [], []
    for row in sections['intro']:
        # Profile link rows contain only the visible anchor labels and separators.
        remainder = row['text']
        for link in reversed(row['links']):
            remainder = remainder[:link['start']] + remainder[link['end']:]
        if row['links'] and not re.sub(r'[\s|·,;:/\[\]]', '', remainder):
            profiles.extend(row['links'])
        else:
            intro.append(row)
    ensure_items(intro, 'research/interest')
    ensure_items(profiles, 'research/academic profiles')
    papers = []
    for key in ('publications', 'preprints'):
        papers += [publication(row, len(papers) + index + 1, key) for index, row in enumerate(sections[key])]
    return {'publications': papers, 'notes': sections['notes'], 'researchIntroItems': intro,
            'researchHeading': headings['intro'], 'publicationHeading': headings['publications'],
            'preprintHeading': headings['preprints'], 'notesHeading': headings['notes'], '_profiles': profiles}


def talk_data(page_blocks: list[Node]) -> dict:
    sections = []
    current = None
    for node in page_blocks:
        row = item(node)
        heading = heading_key(row['text'])
        if node.tag != 'li' and (re.fullmatch(r'talks(?:\s+.+)?', heading) or re.fullmatch(r'reading seminars?', heading)):
            if heading == 'talks':  # Page title is not a content section.
                continue
            current = {'heading': row['text'], 'category': 'reading' if heading.startswith('reading') else 'talk', 'items': []}
            sections.append(current)
        elif node.tag == 'li':
            if current is None:
                raise ParseError('talks: list item before a section heading')
            years = re.findall(r'\b((?:19|20)\d{2})\b', row['text'])
            title, _, detail = row['text'].partition(', ')
            row.update({'title': title, 'detail': detail, 'year': int(years[-1]) if years else None, 'category': current['category']})
            current['items'].append(row)
    if not any(s['category'] == 'talk' for s in sections) or not any(s['category'] == 'reading' for s in sections):
        raise ParseError('talks: missing talks or reading seminar section')
    talks = [row for section in sections for row in section['items']]
    ensure_items(talks, 'talks')
    return {'talkSections': sections, 'talks': talks}


def parse_pages(pages: dict[str, str], previous: dict | None = None) -> dict:
    """Parse all pages atomically, raising ParseError on unsupported structure."""
    missing = set(PAGES) - pages.keys()
    if missing:
        raise ParseError('Missing source pages: ' + ', '.join(sorted(missing)))
    parsed = {page: document(pages[page], page) for page in PAGES}
    _, home_root, home_blocks = parsed['home']
    result = home_data(home_root, home_blocks, previous or {})
    result['source'] = SOURCE_BASE + 'home'
    result.update(research_data(parsed['research'][2]))
    result['profile']['profiles'] = result.pop('_profiles')
    result['profile']['researchInterest'] = ' '.join(i['text'] for i in result['researchIntroItems'])
    result.update(talk_data(parsed['talks'][2]))
    result['teaching'] = [item(n) for n in parsed['teaching'][2] if n.tag == 'li']
    ensure_items(result['teaching'], 'teaching')
    link_blocks = parsed['links'][2]
    collaborator_heading = next((i for i, n in enumerate(link_blocks) if heading_key(text_of(n)) == 'my collaborators'), None)
    if collaborator_heading is None:
        raise ParseError('links: missing collaborators section')
    result['collaboratorHeading'] = text_of(link_blocks[collaborator_heading])
    result['collaborators'] = [item(n) for n in link_blocks[collaborator_heading + 1:] if n.tag == 'li']
    ensure_items(result['collaborators'], 'links/collaborators')
    for row in result['collaborators']:
        match = re.fullmatch(r'(.*?)\s*\((.*)\)', row['text'])
        row.update({'name': match[1].strip() if match else row['text'], 'note': match[2] if match else ''})
    banner = None
    for node in parsed['home'][0].nodes():
        match = re.search(r'background-image\s*:\s*url\([\'"]?([^\)\'\"]+)', node.attrs.get('style') or '', re.I)
        if match and safe_url(match[1]):
            banner = safe_url(match[1])
            break
    if not banner:
        raise ParseError('home: missing banner image')
    result['bannerUrl'] = banner
    return result
