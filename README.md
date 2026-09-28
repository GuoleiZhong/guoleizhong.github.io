# Guolei Zhong's academic homepage

A static version of the [Google Sites homepage](https://sites.google.com/view/guoleizhongshomepage/home), preserving its blue banner, serif typography, page order, academic lists and photograph. The public site is [guoleizhong.github.io](https://guoleizhong.github.io/), maintained in [GuoleiZhong/guoleizhong.github.io](https://github.com/GuoleiZhong/guoleizhong.github.io).

**Automatic synchronization is enabled.** The first cloud synchronization and GitHub Pages deployment succeeded on 28 September 2026. [Verified workflow run](https://github.com/GuoleiZhong/guoleizhong.github.io/actions/runs/36396778395). The repository checks Google Sites every six hours and also supports manual runs.

## Update content in Google Sites

Google Sites is the single source for the homepage's content. Edit the original site and click **Publish**. Drafts are not synchronized. GitHub Actions checks the public site every six hours, without needing this computer to stay on. The target check times in China are 02:17, 08:17, 14:17 and 20:17; GitHub may delay scheduled runs.

The synchronizer covers the five existing pages—Home, Research, Talks, Teaching and Links—the home photograph, banner, and linked public Google Drive PDFs, including the CV. Documents must remain publicly downloadable. Journal articles, academic profiles and other external websites remain links. This is a one-way content sync; editing GitHub does not update Google Sites.

Direct edits to generated HTML, synchronized content JSON, photographs or PDF copies can be overwritten by the next sync. Keep content edits in Google Sites. The layout and styling remain controlled by this repository's `source/build.py` and `assets/style.css`; changing them does not modify Google Sites. Adding pages, changing navigation, renaming sections or restructuring the source site may require an update to `source/google_sites.py` before synchronization can continue.

## Restore or reproduce the cloud setup

The setup below is already active in this repository. To reproduce it in another checkout:

1. Upload the updated `source/` files, including `tests/` and its fixtures, along with any changed public files. Preserve the folder structure. Upload `.github/workflows/sync-google-sites.yml` **last**, after its dependencies are present on `main`.
2. Open **Settings → Pages → Build and deployment → Source** and select **GitHub Actions**. This replaces the existing **Deploy from a branch** setting. The included workflow already supplies the build and deployment.
3. Open **Actions → Sync Google Sites and publish homepage → Run workflow**, choose `main`, and leave `allow_large_removal` unchecked. Verify that both `sync` and `deploy` succeed, then check the live pages and PDFs.

Use **Run workflow** whenever an immediate check or a deployment retry is needed. If a deliberate edit removes more than 40% of a content collection, review the source first, then use the manual `allow_large_removal` option for that specific change.

All parsing, downloads, tests and local-link validation must pass before publication. A failed sync preserves the last deployed website; its error is visible in the Actions run. Unchanged scheduled checks do not redeploy. A monthly successful-operation record in `source/sync-state.json` creates at most one maintenance commit per month when content is unchanged. It documents successful operation and provides repository activity; prolonged failures or manually disabled Actions still need attention. GitHub can disable schedules after 60 days without repository activity.

The workflow uses GitHub's short-lived token and pinned official actions. No Google password or personal access token is required. New Google Sites has no supported Sites API, so this implementation reads public published pages. See the official [Google Sites API limitations](https://developers.google.com/workspace/sites), [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), and [Pages custom workflow setup](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Local maintenance

Open `index.html`, or run `python3 -m http.server 8000` in this folder to preview at `http://localhost:8000/`. To rebuild the layout from the saved content, run `python3 source/build.py`; it needs only the Python standard library.

To run the synchronizer locally, use Python 3.12, install `source/requirements-sync.txt`, then run `python3 source/sync_google_sites.py --root .`. This requires access to Google Sites and Google Drive. Run its offline checks with `python3 -m unittest discover -s source/tests -v`.

## Domain and provenance

`www.zhong-guolei.com` still points to Google Sites. This synchronization setup does not change its DNS or activate a custom domain on GitHub Pages.

Public text, banner, photograph, CV, thesis, notes and slides were migrated from the original site on 26 September 2026 at the site owner's request. The original photo credit is retained. At migration, the site contained 18 linked Google Drive PDFs plus the CV. The JLMS article number for DOI `10.1112/jlms.70646` was corrected to `e70646` against Crossref metadata. A synchronized CV reflects the source PDF and may predate the publication list.

The self-hosted Lora font uses the SIL Open Font License; see `assets/fonts/Lora-LICENSE.txt`. All five pages load without third-party scripts, fonts or images. Visitors need no Python or JavaScript. No analytics or cookies are added.
