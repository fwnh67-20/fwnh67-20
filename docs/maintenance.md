# Maintaining the profile

The profile README and every section image are generated. Edit the content, not the output.

| Path | Role |
| --- | --- |
| `profile/content.json` | All copy: role, practice, method, expertise, career, engagements, credentials |
| `scripts/render.py` | Draws each section as SVG in the Tidal design system and writes `README.md` |
| `scripts/activity.py` | Aggregates GitHub activity for the "Recent activity" card |
| `scripts/fonts.py` | One-off: subsets Inter / Inter Tight and records advance widths |
| `assets/` | Generated section SVGs, plus subset fonts (SIL OFL 1.1, see `assets/fonts/OFL.txt`) |

## Changing content

```sh
python scripts/render.py
python -m unittest discover -s tests
```

Commit `profile/content.json` together with the regenerated `README.md` and `assets/`. The Verify workflow fails if the committed output does not match the content.

Rendering needs only the Python standard library (3.10+).

## Design system

Colours, type and radii mirror the web portfolio's Tidal tokens (`app/globals.css` in the site repository):

- Display: Inter Tight 900. Text: Inter 400 and 600.
- Light: content `#0e0f0c` / `#454745` / `#6a6c6a`, link `#0b5cad`, subtle `#f1f3f0`, mist `#d6ecff`.
- Dark: content `#e8ebe6` / `#c9cbc6` / `#a0a39e`, link `#8ecbff`, subtle `#1a1d19`, mist `#16304a`.
- Bands: blue-deep `#0a2a4d` with blue-bright `#8ecbff` accents in both themes.

Each section is drawn at two widths (880 wide and 400 narrow) for both themes. The README picks one with `<picture>` media queries. Narrow is used below 640px. Theme-independent sections publish a single file.

Fonts are embedded as data URIs, because GitHub serves README images through a proxy that blocks external fonts. If the copy needs characters outside printable ASCII and the punctuation listed in `scripts/fonts.py`, add them there and rerun it against the site's `public/fonts`.

## Activity card

The Activity workflow runs hourly. It collects:

- the time of the latest event or owned-repository push
- contribution totals for the last 30 days and the last 12 months
- the number of repositories pushed in the last 30 days
- their most common primary languages

The script reads repository names only to compute those totals and never writes them, and a unit test guards that. The card and `activity.json` are force-pushed as one commit to the orphan `activity` branch. Main stays clean and the refresh never adds to the contribution graph.

### Token

Private activity needs a token owned by the profile account, stored as the repository secret `PROFILE_ACTIVITY_TOKEN`:

1. GitHub → Settings → Developer settings → Fine-grained personal access tokens → Generate new token.
2. Resource owner: your account. Repository access: All repositories. Permissions: leave the default read-only Metadata.
3. Set an expiry and note the renewal date.
4. In this repository, add it under Settings → Secrets and variables → Actions as `PROFILE_ACTIVITY_TOKEN`.
5. Run the Activity workflow manually (Actions → Activity → Run workflow). Compare the figures with a local run: `GH_TOKEN=$(gh auth token) python scripts/activity.py /tmp/activity.json`.

If the secret is missing or expired, the workflow raises a warning and the card keeps its last published state.

GitHub disables scheduled workflows in repositories with no activity for 60 days. If the card stops updating, re-enable the workflow from the Actions tab.
