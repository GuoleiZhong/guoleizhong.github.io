#!/usr/bin/env python3
"""Build plain HTML with Python 3's standard library. No install is required."""
from html import escape
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'source/content.json').read_text(encoding='utf-8'))
LOCAL = json.loads((ROOT / 'source/local-files.json').read_text(encoding='utf-8'))
NAV = [('index.html', 'Home'), ('research.html', 'Research'), ('talks.html', 'Talks'), ('teaching.html', 'Teaching'), ('links.html', 'Links')]

def esc(value: object) -> str:
    return escape(str(value), quote=True)

def anchor(href: str, label: str) -> str:
    return f'<a href="{esc(LOCAL.get(href, href))}">{esc(label)}</a>'

def link_text(text: str, links: list) -> str:
    """Escape source text, linking original visible labels once."""
    candidates = []
    for item in links:
        bracket = text.find('[' + item['label'] + ']')
        pos = bracket + 1 if bracket >= 0 else text.find(item['label'])
        if pos >= 0:
            candidates.append((pos, pos + len(item['label']), item))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    end, result = 0, ''
    for start, stop, item in candidates:
        if start < end:
            continue
        result += esc(text[end:start]) + anchor(item['url'], item['label'])
        end = stop
    return result + esc(text[end:])

def profiles() -> str:
    return '<div class="profile-links" aria-label="Academic profiles">' + ''.join(anchor(p['url'], p['label']) for p in DATA['profile']['profiles']) + '</div>'

def page(filename: str, title: str, body: str, description: str) -> None:
    is_home = filename == 'index.html'
    nav = ''.join(f'<a href="{path}"' + (' aria-current="page"' if filename == path else '') + f'>{label}</a>' for path, label in NAV)
    heading = '<span>Welcome to the homepage of</span><span class="name-line">Guolei ZHONG <span class="chinese-name" lang="zh-Hans">仲国磊</span></span>' if is_home else esc(title)
    doc_title = 'Guolei ZHONG 仲国磊' if is_home else title + ' | Guolei ZHONG'
    doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{doc_title}</title><meta name="description" content="{esc(description)}"><meta name="author" content="Guolei Zhong">
<meta name="theme-color" content="#29465d"><meta property="og:type" content="website"><meta property="og:title" content="{doc_title}"><meta property="og:description" content="{esc(description)}">
<link rel="icon" type="image/svg+xml" href="assets/favicon.svg"><link rel="stylesheet" href="assets/style.css"><link rel="preload" href="assets/fonts/lora-latin.woff2" as="font" type="font/woff2" crossorigin>
</head><body><a class="skip-link" href="#main">Skip to content</a>
<header class="site-header"><div class="topbar"><a class="site-name" href="index.html">Guolei ZHONG</a><nav class="main-nav" aria-label="Main navigation">{nav}</nav></div>
<div class="banner{' banner-home' if is_home else ''}"><h1>{heading}</h1></div></header>
<main id="main" class="page-content">{body}</main>
<footer class="site-footer">© 2026 Guolei ZHONG <span lang="zh-Hans">仲国磊</span></footer></body></html>'''
    (ROOT / filename).write_text(doc, encoding='utf-8')

def home() -> str:
    profile = DATA['profile']
    bio = ''.join('<li>' + link_text(text, profile['institutionLinks']) + '</li>' for text in profile['bio'][:3])
    bio += '<li>I am working on complex algebraic geometry and its interaction with dynamics. Here is my <a href="files/guolei-zhong-cv.pdf">CV</a>.</li>'
    bio += '<li>Email: <a href="mailto:glzhong@math.ecnu.edu.cn">glzhong[AT]math.ecnu.edu.cn</a>, <a href="mailto:zhongguolei@u.nus.edu">zhongguolei[AT]u.nus.edu</a> (to contact me, please replace [AT] with @)</li>'
    bio += '<li>Phone: +86 021-54342646-621</li><li>Current address: ' + esc(profile['address']) + '</li>'
    return '<section aria-labelledby="about"><h2 class="about-title" id="about">About me</h2><ul class="about-list">' + bio + '</ul></section><figure class="home-photo"><img src="assets/images/guolei-zhong-huangshan.webp" width="1280" height="899" alt="Guolei Zhong on Mount Huangshan, China." decoding="async"><figcaption>' + esc(profile['portraitCredit']) + '</figcaption></figure>'

def publication(item: dict) -> str:
    text = item['sourceText'].replace('Paper No. 170646', 'Paper No. e70646')
    return f'<li id="{esc(item["id"])}">{link_text(text, item["links"])}</li>'

def research() -> str:
    result = '<section class="content-section"><h2 class="section-title">About my research interest:</h2><p>My research interests lie primarily in complex algebraic geometry and its interaction with dynamics.</p>' + profiles() + '</section>'
    for status, heading, section_id in [('published', 'Publication (including accepted papers):', 'publications'), ('preprint', 'Preprints:', 'preprints')]:
        papers = [p for p in DATA['publications'] if (p['status'] == 'preprint') == (status == 'preprint')]
        result += f'<section class="content-section" aria-labelledby="{section_id}"><h2 class="section-title" id="{section_id}">{heading}</h2><ol class="academic-list publication-list">' + ''.join(publication(p) for p in papers) + '</ol></section>'
    result += '<section class="content-section" aria-labelledby="notes"><h2 class="section-title" id="notes">Other texts &amp; notes:</h2><ul class="academic-list notes-list">'
    return result + ''.join('<li>' + link_text(n['text'], n['links']) + '</li>' for n in DATA['notes']) + '</ul></section>'

def talks() -> str:
    result = ''
    for heading, items in [('Talks in 2026:', [t for t in DATA['talks'] if t['category'] == 'talk' and t['year'] == 2026]), ('Talks before 2026:', [t for t in DATA['talks'] if t['category'] == 'talk' and t['year'] != 2026]), ('Reading seminar:', [t for t in DATA['talks'] if t['category'] != 'talk'])]:
        result += '<section class="content-section"><h2 class="section-title">' + heading + '</h2><ul class="academic-list notes-list">'
        result += ''.join('<li>' + link_text(t['text'], t['links']) + '</li>' for t in items) + '</ul></section>'
    return result

def teaching() -> str:
    return '<ul class="academic-list notes-list">' + ''.join('<li>' + link_text(t['text'], t['links']) + '</li>' for t in DATA['teaching']) + '</ul>'

def links() -> str:
    return '<section><h2 class="section-title">My collaborators</h2><ul class="academic-list collaborator-list">' + ''.join('<li>' + link_text(p['text'], p['links']) + '</li>' for p in DATA['collaborators']) + '</ul></section>'

if __name__ == '__main__':
    page('index.html', 'Home', home(), 'Guolei Zhong, Research Professor at East China Normal University. Complex algebraic geometry and its interaction with dynamics.')
    page('research.html', 'Research', research(), 'Publications, preprints, and research notes by Guolei Zhong in complex algebraic geometry and dynamics.')
    page('talks.html', 'Talks', talks(), 'Research talks, lecture slides, and reading seminars by Guolei Zhong.')
    page('teaching.html', 'Teaching', teaching(), 'Teaching by Guolei Zhong at East China Normal University and the National University of Singapore.')
    page('links.html', 'Links', links(), 'Collaborators and mentors of Guolei Zhong.')
    page('404.html', 'Page not found', '<section class="not-found"><p>This page may have moved.</p><p><a href="index.html">Return to the homepage</a></p></section>', 'This page could not be found.')
    for old, dest in [('home', 'index.html'), ('research', 'research.html'), ('talks', 'talks.html'), ('teaching', 'teaching.html'), ('links', 'links.html')]:
        folder = ROOT / old
        folder.mkdir(exist_ok=True)
        (folder / 'index.html').write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0;url=../{dest}"><title>Guolei ZHONG</title></head><body><p>This page has moved. <a href="../{dest}">Continue to the new page</a>.</p></body></html>', encoding='utf-8')
    # GitHub serves 404.html at arbitrary URLs; root-relative links preserve navigation.
    fallback = ROOT / '404.html'
    text = fallback.read_text(encoding='utf-8').replace('href="assets/', 'href="/assets/')
    for filename, label in NAV:
        text = text.replace(f'href="{filename}"', f'href="/{filename}"')
    fallback.write_text(text, encoding='utf-8')
    print('Built 6 pages and 5 legacy redirects.')
