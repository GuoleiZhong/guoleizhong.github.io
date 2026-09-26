# Guolei Zhong's academic homepage

A static, GitHub Pages-ready version of the existing Google Sites homepage, preserving its blue banner, serif typography, page order, academic lists, and photograph.

## Preview

Open `index.html`, or run `python3 -m http.server 8000` in this folder and visit `http://localhost:8000/`.

## Deploy

The confirmed GitHub account is `GuoleiZhong`. Upload this folder's contents (including `.nojekyll`) to the root of the public [`GuoleiZhong/guoleizhong.github.io`](https://github.com/GuoleiZhong/guoleizhong.github.io) repository. In Settings → Pages, select **Deploy from a branch**, **main**, **/(root)**. The default site address will be [https://guoleizhong.github.io/](https://guoleizhong.github.io/). Publication has not yet been confirmed. See the accompanying Chinese `发布说明.md` for setup and custom-domain migration.

No custom domain is activated by this package. The existing `www.zhong-guolei.com` domain still points to Google Sites and will continue to do so until its DNS is changed. Set it in GitHub Pages after checking the default GitHub URL, then update its `www` CNAME target to `guoleizhong.github.io` as described in `发布说明.md`.

## Update

- Content: `source/content.json`
- Local copies of linked documents: `source/local-files.json` and `files/`
- Layout and fixed text: `source/build.py`
- Appearance: `assets/style.css`
- CV: replace `files/guolei-zhong-cv.pdf`

After editing source data or the layout, run `python3 source/build.py`. Only the Python standard library is needed. Upload regenerated HTML along with edited files. Website visitors do not run Python or JavaScript.

## Provenance

Public text, banner, photograph, CV, thesis, notes and slides were migrated from https://sites.google.com/view/guoleizhongshomepage/home and its Research, Talks, Teaching and Links pages on 26 September 2026, at the site owner's request. The original photo credit is retained. All 18 linked Google Drive PDFs are served locally, alongside the original CV. Publication links and collaborators' external websites remain links, not page-loading dependencies.

The Lora font is self-hosted under the SIL Open Font License; see `assets/fonts/Lora-LICENSE.txt`. The JLMS article number for DOI `10.1112/jlms.70646` was corrected to `e70646` against Crossref metadata. The original CV is unchanged and may predate the publication list.

All five pages load without third-party scripts, fonts, images, or JavaScript. No analytics or cookies are added.
