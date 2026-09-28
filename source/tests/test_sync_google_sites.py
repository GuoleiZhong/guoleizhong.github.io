"""Offline integration tests for the staged Google Sites mirror and renderer."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from PIL import Image

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import sync_google_sites as sync
from google_sites import ParseError, parse_pages

FIXTURES = Path(__file__).parent / 'fixtures'
SEPTEMBER = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def pdf_bytes(label: str) -> bytes:
    """A complete one-page PDF, including correct object offsets and xref."""
    label = re.sub(r'[^a-zA-Z0-9 ._-]', '', label)
    stream = f'BT /F1 12 Tf 36 72 Td ({label}) Tj ET'.encode('ascii')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 144 144] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    data = b'%PDF-1.4\n'
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(number).encode() + b' 0 obj\n' + body + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'


def image_bytes() -> bytes:
    out = BytesIO()
    Image.new('RGB', (64, 48), (45, 75, 95)).save(out, 'PNG')
    return out.getvalue()


class FakeGoogle:
    """Public page/PDF/image responses; unknown or missing URLs fail loudly."""
    def __init__(self, pages: dict[str, str]):
        self.pages = deepcopy(pages)
        content = parse_pages(pages)
        urls = sync.item_links(content) | {content['profile']['cv']}
        self.pdfs = {sync.drive_id(url): pdf_bytes(sync.drive_id(url)) for url in urls if sync.drive_id(url)}
        self.images = {content['profile']['portrait']: image_bytes(), content['bannerUrl']: image_bytes()}
        self.requests: list[tuple[str, int]] = []

    def __call__(self, url: str, limit: int) -> bytes:
        self.requests.append((url, limit))
        for page, html in self.pages.items():
            if url == sync.BASE + page:
                return html.encode('utf-8')
        if url in self.images:
            return self.images[url]
        part = urlsplit(url)
        if part.hostname == 'drive.usercontent.google.com':
            identifier = parse_qs(part.query).get('id', [''])[0]
            if identifier not in self.pdfs:
                raise sync.SyncError('Mock public document is missing or private')
            return self.pdfs[identifier]
        raise AssertionError('Unexpected URL in offline test: ' + url)


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class SyncIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {name: (FIXTURES / (name + '.html')).read_text(encoding='utf-8') for name in sync.PAGES}
        cls.base_temp = tempfile.TemporaryDirectory(prefix='guolei-sync-test-base-')
        cls.base = Path(cls.base_temp.name) / 'site'
        for relative in ('source', 'assets/fonts', 'assets/images', 'files'):
            (cls.base / relative).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / 'build.py', cls.base / 'source/build.py')
        content = parse_pages(cls.pages)
        (cls.base / 'source/content.json').write_text(json.dumps(content), encoding='utf-8')
        (cls.base / 'source/local-files.json').write_text('{}', encoding='utf-8')
        for relative in ('assets/style.css', 'assets/fonts/lora-latin.woff2', 'assets/favicon.svg'):
            (cls.base / relative).write_bytes(b'fixture asset')
        with redirect_stdout(StringIO()):
            sync.mirror(cls.base, FakeGoogle(cls.pages), now=SEPTEMBER)

    @classmethod
    def tearDownClass(cls):
        cls.base_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='guolei-sync-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'site'
        shutil.copytree(self.base, self.root)
        self.google = FakeGoogle(self.pages)

    def mirror(self, **kwargs):
        with redirect_stdout(StringIO()):
            return sync.mirror(self.root, self.google, now=kwargs.pop('now', SEPTEMBER), **kwargs)

    def test_unchanged_sync_is_idempotent(self):
        before = tree_bytes(self.root)
        changed = self.mirror(now=datetime(2026, 9, 29, tzinfo=timezone.utc))
        self.assertEqual(changed, [])
        self.assertEqual(tree_bytes(self.root), before)
        pdf_requests = [url for url, _ in self.google.requests if 'drive.usercontent.google.com' in url]
        self.assertEqual(len(pdf_requests), len(self.google.pdfs))

    def test_changed_text_and_new_cv_url_are_published_together(self):
        old = json.loads((self.root / 'source/content.json').read_text())
        old_cv = old['profile']['cv']
        new_id = 'NewPublicCurriculumVitae012345'
        new_cv = 'https://drive.google.com/file/d/' + new_id + '/view?usp=sharing'
        self.google.pages['home'] = self.google.pages['home'].replace(old_cv, new_cv).replace('Room 221', 'Room 321')
        new_pdf = pdf_bytes('New curriculum vitae')
        self.google.pdfs[new_id] = new_pdf
        changed = self.mirror()
        data = json.loads((self.root / 'source/content.json').read_text())
        self.assertEqual(data['profile']['cv'], new_cv)
        self.assertIn('Room 321', (self.root / 'index.html').read_text())
        self.assertIn('href="files/guolei-zhong-cv.pdf">CV</a>', (self.root / 'index.html').read_text())
        self.assertEqual((self.root / 'files/guolei-zhong-cv.pdf').read_bytes(), new_pdf)
        self.assertTrue({'index.html', 'source/content.json', 'source/local-files.json', 'files/guolei-zhong-cv.pdf'} <= set(changed))

    def test_replaced_cv_and_archived_old_cv_keep_separate_files(self):
        data = json.loads((self.root / 'source/content.json').read_text())
        old_cv = data['profile']['cv']
        old_pdf = self.google.pdfs[sync.drive_id(old_cv)]
        new_id = 'ReplacementCurriculumVitae012345'
        new_cv = 'https://drive.google.com/file/d/' + new_id + '/view'
        new_pdf = pdf_bytes('Current CV with archived previous version')
        self.google.pdfs[new_id] = new_pdf
        self.google.pages['home'] = self.google.pages['home'].replace(old_cv, new_cv)
        archive = '<li>Archived document: <a href="' + old_cv + '">Previous CV</a></li>'
        self.google.pages['research'] = self.google.pages['research'].replace('</ul>', archive + '</ul>', 1)
        self.mirror()
        mapping = json.loads((self.root / 'source/local-files.json').read_text())
        self.assertNotEqual(mapping[old_cv], mapping[new_cv])
        self.assertEqual((self.root / mapping[old_cv]).read_bytes(), old_pdf)
        self.assertEqual((self.root / mapping[new_cv]).read_bytes(), new_pdf)

    def test_same_drive_id_with_updated_pdf_bytes_is_detected(self):
        data = json.loads((self.root / 'source/content.json').read_text())
        identifier = sync.drive_id(data['profile']['cv'])
        replacement = pdf_bytes('Updated CV using the same Drive file id')
        self.google.pdfs[identifier] = replacement
        old_home = (self.root / 'index.html').read_bytes()
        self.assertEqual(self.mirror(), ['files/guolei-zhong-cv.pdf'])
        self.assertEqual((self.root / 'files/guolei-zhong-cv.pdf').read_bytes(), replacement)
        self.assertEqual((self.root / 'index.html').read_bytes(), old_home)

    def test_missing_invalid_or_truncated_pdf_leaves_entire_root_unchanged(self):
        identifier = sorted(self.google.pdfs)[-1]  # Earlier resources may already have staged writes.
        cases = [None, b'<html>Sign in to view this file</html>', b'%PDF-1.7\nIncomplete response']
        for response in cases:
            with self.subTest(response=response):
                self.google = FakeGoogle(self.pages)
                self.google.pages['home'] = self.google.pages['home'].replace('Room 221', 'Room 321')
                if response is None:
                    del self.google.pdfs[identifier]
                else:
                    self.google.pdfs[identifier] = response
                before = tree_bytes(self.root)
                with self.assertRaises(sync.SyncError):
                    self.mirror()
                self.assertEqual(tree_bytes(self.root), before)

    def test_fetch_parse_image_build_and_validation_failures_roll_back(self):
        before = tree_bytes(self.root)
        self.google.pages['research'] = '<html><title>Temporarily unavailable</title></html>'
        with self.assertRaises(ParseError):
            self.mirror()
        self.assertEqual(tree_bytes(self.root), before)
        self.google = FakeGoogle(self.pages)
        self.google.images = {url: b'Not an image' for url in self.google.images}
        with self.assertRaises(sync.SyncError):
            self.mirror()
        self.assertEqual(tree_bytes(self.root), before)
        self.google = FakeGoogle(self.pages)
        self.google.pages['home'] = self.google.pages['home'].replace('Room 221', 'Room 321')
        with patch.object(sync.runpy, 'run_path', side_effect=RuntimeError('Build failed')):
            with self.assertRaises(RuntimeError):
                self.mirror()
        self.assertEqual(tree_bytes(self.root), before)
        with patch.object(sync, 'validate_site', side_effect=sync.SyncError('Validation failed')):
            with self.assertRaises(sync.SyncError):
                self.mirror()
        self.assertEqual(tree_bytes(self.root), before)
        def failed_fetch(*_):
            raise sync.SyncError('Fetch failed')
        with self.assertRaises(sync.SyncError):
            sync.mirror(self.root, failed_fetch, now=SEPTEMBER)
        self.assertEqual(tree_bytes(self.root), before)

    def test_large_removal_requires_explicit_allow_flag(self):
        matches = list(re.finditer(r'<li\b[^>]*>.*?</li>', self.google.pages['teaching'], re.S))
        self.assertEqual(len(matches), 7)
        for match in reversed(matches[2:]):
            self.google.pages['teaching'] = self.google.pages['teaching'][:match.start()] + self.google.pages['teaching'][match.end():]
        before = tree_bytes(self.root)
        with self.assertRaisesRegex(sync.SyncError, 'Unexpected loss of teaching'):
            self.mirror()
        self.assertEqual(tree_bytes(self.root), before)
        changed = self.mirror(allow_large_removal=True)
        self.assertIn('teaching.html', changed)
        current = json.loads((self.root / 'source/content.json').read_text())
        self.assertEqual(len(current['teaching']), 2)

    def test_unsafe_download_redirects_and_local_paths_are_rejected(self):
        unsafe_urls = ['http://sites.google.com/page', 'https://evil.example/file', 'https://127.0.0.1/file',
                       'file:///etc/passwd', 'https://sites.google.com.evil.example/file',
                       'https://evil.googleusercontent.com.evil.example/file',
                       'https://user:password@sites.google.com/page', 'https://sites.google.com:444/page']
        handler = sync.SafeRedirect()
        request = Request(sync.BASE + 'home')
        for url in unsafe_urls:
            with self.subTest(url=url):
                self.assertFalse(sync.allowed_google_url(url))
                with self.assertRaises(sync.SyncError):
                    handler.redirect_request(request, None, 302, 'Found', {}, url)
        for path in ('../outside.pdf', '/tmp/outside.pdf', 'files/../outside.pdf', 'files/nested/outside.pdf', 'files/a.html', 'files/a.pdf.sync-tmp'):
            with self.subTest(path=path):
                self.assertFalse(sync.public_pdf_path(path))
                map_path = self.root / 'source/local-files.json'
                mapping = json.loads(map_path.read_text())
                mapping[next(iter(mapping))] = path
                map_path.write_text(json.dumps(mapping))
                before = tree_bytes(self.root)
                with self.assertRaises(sync.SyncError):
                    self.mirror()
                self.assertEqual(tree_bytes(self.root), before)

    def test_future_year_and_untrusted_text_render_as_source_text(self):
        self.google.pages['talks'] = self.google.pages['talks'].replace('2026', '2027')
        self.google.pages['talks'] = re.sub(r'<p><span>Talks before.*?</p>', '<p>Talks before 2027:</p>', self.google.pages['talks'])
        self.google.pages['home'] = self.google.pages['home'].replace('Room 221', 'Room 321 &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; test')
        self.mirror()
        talk_html = (self.root / 'talks.html').read_text()
        home_html = (self.root / 'index.html').read_text()
        self.assertIn('Talks in 2027:', talk_html)
        self.assertIn('Talks before 2027:', talk_html)
        self.assertNotIn('Talks in 2026:', talk_html)
        self.assertIn('&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; test', home_html)
        self.assertNotIn('<script>', home_html)
        sync.validate_site(self.root)

    def test_academic_profile_links_survive_dynamic_rendering(self):
        html = (self.root / 'research.html').read_text()
        from html import escape
        for link in parse_pages(self.pages)['profile']['profiles']:
            self.assertIn('href="' + escape(link['url'], quote=True) + '"', html)

    def test_monthly_health_rollover_changes_only_state(self):
        old_content = (self.root / 'source/content.json').read_bytes()
        changed = self.mirror(now=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(changed, ['source/sync-state.json'])
        state = json.loads((self.root / 'source/sync-state.json').read_text())
        self.assertEqual(state['last_successful_month'], '2026-10')
        self.assertEqual((self.root / 'source/content.json').read_bytes(), old_content)
        self.assertEqual(self.mirror(now=datetime(2026, 10, 5, tzinfo=timezone.utc)), [])


if __name__ == '__main__':
    unittest.main()
