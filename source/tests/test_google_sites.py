"""Regression fixtures are the five real published pages, with UI/scripts stripped."""
from copy import deepcopy
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google_sites import DocumentParser, ParseError, item, parse_pages, safe_url

FIXTURES = Path(__file__).parent / 'fixtures'
PAGES = ('home', 'research', 'talks', 'teaching', 'links')


class GoogleSitesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {p: (FIXTURES / (p + '.html')).read_text(encoding='utf-8') for p in PAGES}
        cls.content = parse_pages(cls.pages)

    def test_real_published_content_and_links(self):
        data = self.content
        self.assertEqual(len(data['homeItems']), 7)
        self.assertEqual(len(data['publications']), 21)
        self.assertEqual([p['status'] for p in data['publications']].count('preprint'), 3)
        self.assertEqual(len(data['notes']), 2)
        self.assertEqual(len(data['talks']), 46)
        self.assertEqual(len(data['teaching']), 7)
        self.assertEqual(len(data['collaborators']), 17)
        self.assertEqual(len(data['profile']['profiles']), 7)
        self.assertEqual(data['profile']['emails'], ['glzhong@math.ecnu.edu.cn', 'zhongguolei@u.nus.edu'])
        self.assertIn('Room 221', data['profile']['address'])
        self.assertIn('28 March 2026', data['profile']['portraitCredit'])
        self.assertIn('sitesv-images', data['profile']['portrait'])
        self.assertIn('sitesv-images', data['bannerUrl'])
        self.assertEqual([s['heading'] for s in data['talkSections']], ['Talks in 2026:', 'Talks before 2026:', 'Reading seminar:'])
        self.assertEqual(data['publications'][2]['sourceText'].count('170646'), 1)
        for group in ('homeItems', 'researchIntroItems', 'notes', 'talks', 'teaching', 'collaborators', 'publications'):
            for row in data[group]:
                text = row.get('text', row.get('sourceText'))
                for link in row['links']:
                    self.assertEqual(text[link['start']:link['end']], link['label'])
                    self.assertIsNotNone(safe_url(link['url']))

    def test_missing_or_wrong_page_identity_is_rejected(self):
        cases = [('home', 'role="main"', 'role="region"'),
                 ('research', '<title>Guolei ZHONG - Research</title>', '<title>Sign in</title>'),
                 ('talks', '>Talks</span>', '>Unexpected</span>')]
        for page, old, new in cases:
            with self.subTest(page=page):
                pages = deepcopy(self.pages)
                self.assertIn(old, pages[page])
                pages[page] = pages[page].replace(old, new)
                with self.assertRaises(ParseError):
                    parse_pages(pages, self.content)
        with self.assertRaises(ParseError):
            parse_pages({'home': self.pages['home']})

    def test_missing_sections_fail_closed(self):
        cases = [('home', 'About me', 'Biography'), ('research', 'Preprints', 'Drafts'),
                 ('research', 'Other texts &amp; notes', 'Unrecognized section'),
                 ('talks', 'Reading seminar:', 'Unrecognized section:'),
                 ('links', 'My collaborators', 'People')]
        for page, old, new in cases:
            with self.subTest(page=page, section=old):
                pages = deepcopy(self.pages)
                self.assertIn(old, pages[page])
                pages[page] = pages[page].replace(old, new)
                with self.assertRaises(ParseError):
                    parse_pages(pages, self.content)

    def test_future_year_and_additions_use_headings_not_fixed_indices(self):
        pages = deepcopy(self.pages)
        pages['talks'] = pages['talks'].replace('2026', '2027')
        pages['talks'] = re.sub(r'<p><span>Talks before.*?</p>', '<p>Talks before 2027:</p>', pages['talks'])
        first_list = pages['talks'].index('<ul')
        first_item = pages['talks'].index('<li', first_list)
        pages['talks'] = pages['talks'][:first_item] + '<li>New talk, New University, 4 March 2027. <a href="https://example.org/talk.pdf">slides</a></li>' + pages['talks'][first_item:]
        first_paper = pages['research'].index('<li')
        pages['research'] = pages['research'][:first_paper] + '<li>New paper, New Journal (to appear). <a href="https://arxiv.org/abs/2701.00001">arXiv</a></li>' + pages['research'][first_paper:]
        result = parse_pages(pages, self.content)
        self.assertEqual(result['talkSections'][0]['heading'], 'Talks in 2027:')
        self.assertEqual(len(result['talks']), 47)
        self.assertEqual(result['talks'][0]['year'], 2027)
        self.assertEqual(len(result['publications']), 22)
        self.assertEqual(result['publications'][0]['status'], 'accepted')
        self.assertEqual(sum(p['status'] == 'preprint' for p in result['publications']), 3)
        self.assertEqual([p['sourceOrder'] for p in result['publications']], list(range(1, 23)))

    def test_all_preprints_can_move_to_publications_without_losing_items(self):
        pages = deepcopy(self.pages)
        source = pages['research']
        match = re.search(r'(<p><span>Preprints</span><span>:\s*</span></p><ol>)(.*?)(</ol>)', source)
        self.assertIsNotNone(match)
        source = source[:match.start(2)] + source[match.end(2):]
        first_end = source.index('</ol>')
        pages['research'] = source[:first_end] + match[2] + source[first_end:]
        data = parse_pages(pages, self.content)
        self.assertEqual(len(data['publications']), len(self.content['publications']))
        self.assertFalse(any(p['status'] == 'preprint' for p in data['publications']))
        self.assertEqual(data['preprintHeading'], 'Preprints:')

    def test_empty_notes_and_future_year_sections_are_supported(self):
        pages = deepcopy(self.pages)
        pages['research'] = re.sub(r'<ul>.*?</ul>', '<ul></ul>', pages['research'], count=1)
        pages['talks'] = re.sub(r'<ul>.*?</ul>', '<ul></ul>', pages['talks'], count=1)
        pages['talks'] = pages['talks'].replace('2026', '2027')
        pages['talks'] = re.sub(r'<p><span>Talks before.*?</p>', '<p>Talks before 2027:</p>', pages['talks'])
        data = parse_pages(pages, self.content)
        self.assertEqual(data['notes'], [])
        self.assertEqual(data['talkSections'][0]['heading'], 'Talks in 2027:')
        self.assertEqual(data['talkSections'][0]['items'], [])
        self.assertTrue(data['talks'])

    def test_new_contact_replaces_previous_metadata(self):
        pages = deepcopy(self.pages)
        pages['home'] = pages['home'].replace('glzhong[AT]math.ecnu.edu.cn', 'new[AT]example.org').replace('Room 221', 'Room 321')
        previous = deepcopy(self.content)
        previous['profile']['position'] = 'Stale position'
        data = parse_pages(pages, previous)
        self.assertIn('new@example.org', data['profile']['emails'])
        self.assertNotIn('glzhong@math.ecnu.edu.cn', data['profile']['emails'])
        self.assertIn('Room 321', data['profile']['address'])
        self.assertNotIn('position', data['profile'])
        self.assertEqual(previous['profile']['position'], 'Stale position')

    def test_executable_links_and_script_text_are_discarded(self):
        p = DocumentParser()
        p.feed('<li>Keep <a href="javascript:alert(1)">bad</a> <script>secret</script><a href="https://example.org/ok">safe</a> <a href="mailto:a@example.org">mail</a></li>')
        row = item(p.root)
        self.assertEqual(row['text'], 'Keep bad safe mail')
        self.assertEqual([l['label'] for l in row['links']], ['safe', 'mail'])
        for value in ('javascript:alert(1)', 'data:text/html,x', '//example.org', 'https://user:pass@example.org', 'https://example.org\\@evil.org', 'https://example.org:bad/', 'mailto:a@example.org?subject=x%0d%0aBcc:x@evil.org', 'java\nscript:alert(1)'):
            with self.subTest(url=value):
                self.assertIsNone(safe_url(value))

    def test_duplicate_anchor_labels_keep_exact_offsets(self):
        p = DocumentParser()
        p.feed('<li>Journal of Geometry. [<a href="https://example.org/journal">Journal</a>][<a href="https://example.org/other">Journal</a>]</li>')
        row = item(p.root)
        self.assertEqual([l['start'] for l in row['links']], [22, 31])
        for link in row['links']:
            self.assertEqual(row['text'][link['start']:link['end']], 'Journal')

    def test_optional_full_original_snapshots_match(self):
        # Development additionally compares complete responses including Google UI.
        workspace = Path(__file__).resolve().parents[4]
        paths = {p: workspace / 'work' / ('original-' + p + '.html') for p in PAGES}
        if not all(p.exists() for p in paths.values()):
            self.skipTest('Full source snapshots are only present in the development workspace')
        full = parse_pages({k: p.read_text(encoding='utf-8') for k, p in paths.items()})
        self.assertEqual(full, self.content)


if __name__ == '__main__':
    unittest.main()
