# FitGirl FuckingFast Link Extractor

A lightweight, threaded desktop GUI tool built in Python to retrieve, filter, and extract direct download links from FuckingFast hosters on FitGirl Repack pages and [paste.fitgirl-repacks.site](https://paste.fitgirl-repacks.site) PrivateBin pastes.

Works on **Windows and Linux**, and lets you pick whichever Chromium-based browser you already have installed.

## Features
- **Paste support:** Decrypts FitGirl PrivateBin URLs (`?id#key`) and pulls every `fuckingfast.co` link.
- **HTML / raw links:** Accepts pasted `<a href="https://fuckingfast.co/...">` snippets or plain FF URLs.
- **Fast Parsing:** Instantly pulls files, setup binaries, and optional parts.
- **Selective Scrape:** Use checkboxes to exclude unwanted files (like bonus content, other languages, etc.) before running the slow browser extraction process.
- **Cloudflare Bypass:** Employs an undetected Chromium browser process to seamlessly pass Turnstile checks.
- **Browser choice:** Auto-detects installed Chromium browsers, or pick one up front with `--browser`.
- **Copy-to-Clipboard:** One button copies all successfully resolved direct URLs for direct import into JDownloader 2, IDM, or Free Download Manager.

## Download (Pre-compiled Executable)
If you don't have Python installed, simply download the latest standalone `.exe` from our [Releases Page](https://github.com/zouhirdev/fitgirl-ff-link-extractor/releases).

## Running from Source
1. Clone this repository:
   ```bash
   git clone https://github.com/zouhirdev/fitgirl-ff-link-extractor.git
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

On Linux you also need Tkinter (for the GUI), e.g. `sudo apt install python3-tk` on Debian/Ubuntu or `sudo pacman -S tk` on Arch.

## Choosing a Browser
The GUI auto-detects the Chromium-based browsers installed on your machine. To choose one before the window opens, pass `--browser` with any command that works in your terminal:

```bash
python ff_grabber.py --list-browsers        # show what was detected
python ff_grabber.py --browser chromium
python ff_grabber.py --browser helium-browser
python ff_grabber.py --browser brave-browser
python ff_grabber.py --browser google-chrome
python ff_grabber.py --browser /usr/bin/chromium
```

The chosen browser is preselected in the GUI dropdown. On Windows the same flag accepts `chrome`, `brave`, or a full path such as `C:\Program Files\Google\Chrome\Application\chrome.exe`.

> **Note:** Only Chromium-based browsers are supported for now (Google Chrome, Brave, Chromium, Helium, Vivaldi, Opera). Firefox-based browsers such as Zen, LibreWolf, Waterfox and Floorp are not supported yet.
