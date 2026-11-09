# FitGirl FuckingFast Link Extractor

> **This fork is Linux-first.** The main focus here is getting the extractor working on Linux with whichever Chromium-based browser you already have installed. It still runs on Windows.

A lightweight, threaded desktop GUI tool built in Python to retrieve, filter, and extract direct download links from FuckingFast hosters on FitGirl Repack pages and [paste.fitgirl-repacks.site](https://paste.fitgirl-repacks.site) PrivateBin pastes.

## Linux Quick Start (main focus)

You need Python 3, Tkinter, and a Chromium-based browser.

**Arch:**
```bash
sudo pacman -S tk chromium
```

**Debian / Ubuntu:**
```bash
sudo apt install python3-tk chromium
```

Then clone, install, and run:

```bash
git clone https://github.com/dev-rudran/fitgirl-ff-link-extractor.git
cd fitgirl-ff-link-extractor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python ff_grabber.py --list-browsers     # show detected browsers
python ff_grabber.py --browser chromium
python ff_grabber.py --browser chromium --save   # also save <game name>.txt
```

`--save` writes the resolved direct links to `<game name>.txt` in the current directory (game name taken from the FitGirl page). You can also tick **Auto-save links to &lt;game name&gt;.txt** in the GUI.

`--browser` accepts any command you can run in your terminal, or a full path:

```bash
python ff_grabber.py --browser helium-browser
python ff_grabber.py --browser brave-browser
python ff_grabber.py --browser google-chrome
python ff_grabber.py --browser /usr/bin/chromium
```

The chosen browser is preselected in the GUI dropdown.

> **Scope:** Only Chromium-based browsers are supported for now (Google Chrome, Brave, Chromium, Helium, Vivaldi, Opera). Firefox-based browsers such as Zen, LibreWolf, Waterfox and Floorp are not supported yet.

## Features
- **Paste support:** Decrypts FitGirl PrivateBin URLs (`?id#key`) and pulls every `fuckingfast.co` link.
- **HTML / raw links:** Accepts pasted `<a href="https://fuckingfast.co/...">` snippets or plain FF URLs.
- **Fast Parsing:** Instantly pulls files, setup binaries, and optional parts.
- **Selective Scrape:** Use checkboxes to exclude unwanted files (like bonus content, other languages, etc.) before running the slow browser extraction process.
- **Cloudflare Bypass:** Employs an undetected Chromium browser process to seamlessly pass Turnstile checks.
- **Browser choice:** Auto-detects installed Chromium browsers, or pick one up front with `--browser`.
- **Auto-save:** Writes resolved links to `<game name>.txt` with `--save` or the GUI checkbox.
- **Copy-to-Clipboard:** One button copies all successfully resolved direct URLs for direct import into JDownloader 2, IDM, or Free Download Manager.

## Download (Windows Executable)
If you don't have Python installed, download the latest standalone `.exe` from our [Releases Page](https://github.com/zouhirdev/fitgirl-ff-link-extractor/releases).

## Running from Source (Windows / macOS / Linux)
1. Clone this repository:
   ```bash
   git clone https://github.com/dev-rudran/fitgirl-ff-link-extractor.git
   cd fitgirl-ff-link-extractor
   ```
2. Set up your environment and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the script:
   ```bash
   python ff_grabber.py
   ```

On Windows, `--browser` also accepts `chrome`, `brave`, or a full path such as `C:\Program Files\Google\Chrome\Application\chrome.exe`.
