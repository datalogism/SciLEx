# Desktop application

<img src="../_static/modules/emblem.png" alt="SciLEx emblem" height="72" align="right">

The SciLEx desktop application runs a whole literature review without the command
line: configure and collect, screen against eligibility criteria, annotate in a shared
Zotero group, extend and enrich the corpus, analyse it and export a knowledge graph.
It works on the same files as the CLI: a review is a folder containing a
`scilex.yml`, and API keys live in `~/.config/scilex/keys.yml`. You can switch between
the app and the `scilex-*` commands at any time.

Each screen is documented as a [module](../modules/index.md).

## Install

Download the archive for your system from the
[latest release](https://github.com/Wimmics/SciLEx/releases/latest), then:

- **macOS** (`SciLEx-macos.dmg`): open the image and drag `SciLEx.app` to Applications.
  The app is not signed yet: the first time, right-click the app, choose **Open**, then
  **Open** again in the warning dialog.
- **Windows** (`SciLEx-windows.zip`): extract the folder and run `SciLEx.exe`.
  SmartScreen may warn about an unknown publisher: click **More info**, then **Run
  anyway**. A single-file `SciLEx.exe` can also be built with
  `scripts/build_exe_desktop.ps1`.
- **Linux** (`SciLEx-linux.tar.gz`, needs glibc 2.34+, e.g. Ubuntu 22.04 or later):
  extract it and run `SciLEx/SciLEx`. If the window cannot open (no display, missing
  system library), the app says why and opens in your web browser instead.

From a development checkout:

```bash
uv sync --extra gui
uv run scilex-gui              # native window
uv run scilex-gui --browser    # same UI in a browser tab (--port N, --no-open)
uv run scilex-gui --self-test  # check the installation without opening a window
scripts/build_gui.sh           # standalone app with PyInstaller (dist/), then self-test
```

Maintainers publish a release by pushing a `gui-v*` tag (for example
`git tag gui-v0.1.0 && git push origin gui-v0.1.0`): the "GUI build" workflow builds the
three archives, self-tests them and attaches them to the GitHub Release of that tag.

## First steps

1. **ORCID iD** — the app asks for it first and stays locked without it
   ([Workspace → ORCID profile](../modules/workspace.md#orcid-profile)).
2. **API keys** — once for all reviews, including the global Zotero access key
   ([Workspace → API keys](../modules/workspace.md#api-keys)).
3. **New review** — from scratch, from Zotero or from a knowledge graph
   ([Workspace → Reviews](../modules/workspace.md#reviews)).
4. **Zotero group** — choose the review's dedicated group
   ([Zotero → Zotero group](../modules/zotero.md#zotero-group)).
5. Follow the steps of the sidebar.

## The sidebar of a review

| Step | Module | Opens |
|---|---|---|
| Overview | [Overview](../modules/overview.md) | always (first page of a review) |
| Explore | [Explore](../modules/explore.md) | once the review has papers |
| ① Configure | [Configure](../modules/configure.md) | always (also when `scilex.yml` is invalid) |
| ② Collect | [Collect](../modules/collect.md) | until the review has papers, then in ⑤ Extend |
| Eligibility criteria | [Criteria](../modules/criteria.md) | once the review has papers |
| ③ Screen | [Screen](../modules/screen.md) | once the review has papers |
| ④ Annotate | [Annotate](../modules/annotate.md) | always |
| ⑤ Extend | [Extend](../modules/extend.md) | once the review has papers |
| Consolidate | [Consolidate](../modules/consolidate.md) | once the review has papers |
| ⑥ Enrich | [Enrich](../modules/enrich.md) | once the review has papers |
| ⑦ Analyses | [Analyses](../modules/analyses.md) | once the review has papers |
| ⑧ Export | [Export](../modules/export.md) | once the review has papers |
| Zotero group | [Zotero](../modules/zotero.md) | always |
| API keys | [Workspace](../modules/workspace.md#api-keys) | always (the review's overrides) |

Locked steps unlock by themselves as soon as an aggregation writes its results, without
reloading the page. Above the sidebar, next to the review's name, sit the Zotero
[sync icon](../modules/zotero.md#sync) (once the review has papers) and the
[running-jobs button](../modules/workspace.md#running-jobs).

## Troubleshooting

- Check an installation without opening a window: run the executable with
  `--self-test` (for example `SciLEx.app/Contents/MacOS/SciLEx --self-test` on macOS).
- Logs are written to `scilex-gui.log` in your user log folder
  (`~/Library/Logs/scilex` on macOS, `%LOCALAPPDATA%\scilex\Logs` on Windows,
  `~/.local/state/scilex/log` on Linux).
- Unexpected errors show a dialog with **Copy diagnostics**: paste it into a GitHub
  issue.
- An app built before a new `scilex.yml` key reports it as unknown and offers to remove
  it: update the app rather than accepting.
- See also the general [troubleshooting guide](../getting-started/troubleshooting.md).
