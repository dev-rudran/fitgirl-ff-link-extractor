import setuptools  # Register distutils fallback
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zlib
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import base58
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

FF_LINK_RE = re.compile(
    r"https?://(?:www\.)?fuckingfast\.co/[^\s\"'<>\]]+",
    re.IGNORECASE,
)
PASTE_URL_RE = re.compile(
    r"https?://paste\.fitgirl-repacks\.site/\?[0-9a-fA-F]+#[A-Za-z0-9]+",
    re.IGNORECASE,
)


def extract_ff_links(text):
    """Pull unique fuckingfast.co URLs from HTML, markdown, or plain text."""
    links = []
    seen = set()
    for match in FF_LINK_RE.findall(text or ""):
        url = match.rstrip(").,;]")
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def decrypt_privatebin_paste(paste_url):
    """
    Decrypt a PrivateBin v2 paste (FitGirl pastebin).
    URL form: https://paste.fitgirl-repacks.site/?<id>#<base58-key>
    """
    paste_url = paste_url.strip()
    if "?" not in paste_url or "#" not in paste_url:
        raise ValueError("Paste URL must include ?pasteid#key")

    base, rest = paste_url.split("?", 1)
    pasteid, key_b58 = rest.split("#", 1)
    pasteid = pasteid.split("&")[0].replace("pasteid=", "")
    key_b58 = key_b58.split("&")[0].strip()
    key = base58.b58decode(key_b58)
    if len(key) != 32:
        raise ValueError(f"Invalid paste key length: {len(key)} (expected 32)")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "X-Requested-With": "JSONHttpRequest",
    }
    api_url = f"{base.rstrip('/')}/?{pasteid}"
    res = requests.get(api_url, headers=headers, timeout=20)
    res.raise_for_status()
    data = res.json()
    if data.get("status", 0) != 0:
        raise ValueError(f"Paste API error: {data.get('message', data)}")

    adata = data["adata"]
    iv_b64, salt_b64, iterations, key_bits, tag_bits, _cipher, _mode, compression = adata[0]
    iv = base64.b64decode(iv_b64)
    salt = base64.b64decode(salt_b64)
    ciphertext = base64.b64decode(data["ct"])
    aad = json.dumps(adata, separators=(",", ":")).encode("utf-8")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=key_bits // 8,
        salt=salt,
        iterations=int(iterations),
    )
    aes_key = kdf.derive(key)
    plain = AESGCM(aes_key).decrypt(iv, ciphertext, aad)

    if compression == "zlib":
        try:
            plain = zlib.decompress(plain, -zlib.MAX_WBITS)
        except zlib.error:
            plain = zlib.decompress(plain)
    elif compression not in (None, "none"):
        raise ValueError(f"Unsupported paste compression: {compression}")

    payload = json.loads(plain.decode("utf-8"))
    return payload.get("paste", "")


# ---------------------------------------------------------------------------
# Browser discovery and selection (Chromium-based browsers only, for now)
#
# Any Chromium browser you can launch from a terminal works on Linux, e.g.
#     python ff_grabber.py --browser chromium
#     python ff_grabber.py --browser helium-browser
#     python ff_grabber.py --browser brave-browser
# A full path also works. Known browsers are auto-detected for the GUI list.
# ---------------------------------------------------------------------------

CHROMIUM = "chromium"
FIREFOX = "firefox"
EDGE = "edge"

# Ordered roughly by how well each engine gets through Cloudflare Turnstile.
BROWSER_SPECS = [
    {
        "key": "chrome",
        "label": "Google Chrome",
        "engine": CHROMIUM,
        "commands": ("google-chrome", "google-chrome-stable", "chrome"),
        "windows": (
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        ),
        "macos": ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",),
        "linux": (
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
        ),
        "flatpak": ("com.google.Chrome",),
    },
    {
        "key": "brave",
        "label": "Brave",
        "engine": CHROMIUM,
        "commands": ("brave-browser", "brave"),
        "windows": (
            r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
        ),
        "macos": ("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",),
        "linux": (
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
            "/opt/brave.com/brave/brave",
        ),
        "flatpak": ("com.brave.Browser",),
    },
    {
        "key": "chromium",
        "label": "Chromium",
        "engine": CHROMIUM,
        "commands": ("chromium", "chromium-browser", "chromium-freeworld"),
        "windows": (
            r"%ProgramFiles%\Chromium\Application\chrome.exe",
            r"%LocalAppData%\Chromium\Application\chrome.exe",
        ),
        "macos": ("/Applications/Chromium.app/Contents/MacOS/Chromium",),
        "linux": (
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/lib/chromium/chromium",
            "/snap/bin/chromium",
        ),
        "flatpak": ("org.chromium.Chromium",),
    },
    {
        "key": "helium",
        "label": "Helium",
        "engine": CHROMIUM,
        "commands": ("helium-browser", "helium"),
        "windows": (
            r"%ProgramFiles%\Helium\Application\helium.exe",
            r"%ProgramFiles%\Helium\Application\chrome.exe",
            r"%LocalAppData%\Helium\Application\helium.exe",
            r"%LocalAppData%\Helium\Application\chrome.exe",
        ),
        "macos": ("/Applications/Helium.app/Contents/MacOS/Helium",),
        "linux": (
            "/usr/bin/helium-browser",
            "/usr/bin/helium",
            "/opt/helium-browser-bin/helium",
            "/opt/helium/helium",
        ),
        "flatpak": (),
    },
    {
        "key": "vivaldi",
        "label": "Vivaldi",
        "engine": CHROMIUM,
        "commands": ("vivaldi", "vivaldi-stable"),
        "windows": (
            r"%LocalAppData%\Vivaldi\Application\vivaldi.exe",
            r"%ProgramFiles%\Vivaldi\Application\vivaldi.exe",
        ),
        "macos": ("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",),
        "linux": (
            "/usr/bin/vivaldi",
            "/usr/bin/vivaldi-stable",
            "/opt/vivaldi/vivaldi",
        ),
        "flatpak": ("com.vivaldi.Vivaldi",),
    },
    {
        "key": "opera",
        "label": "Opera",
        "engine": CHROMIUM,
        "commands": ("opera", "opera-stable"),
        "windows": (
            r"%LocalAppData%\Programs\Opera\opera.exe",
            r"%ProgramFiles%\Opera\opera.exe",
        ),
        "macos": ("/Applications/Opera.app/Contents/MacOS/Opera",),
        "linux": (
            "/usr/bin/opera",
            "/usr/lib/x86_64-linux-gnu/opera/opera",
            "/opt/opera/opera",
        ),
        "flatpak": ("com.opera.Opera",),
    },
]


class BrowserNotFound(Exception):
    def __init__(self, value):
        self.value = value
        super().__init__(value)


class BrowserUnsupported(Exception):
    def __init__(self, value, label=None, engine=None):
        self.value = value
        self.label = label or value
        self.engine = engine
        super().__init__(value)


def _current_os():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _normalize(value):
    """Normalize a browser name/path so 'Google Chrome', 'google chrome' and 'google-chrome' match."""
    name = os.path.basename((value or "").strip()).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return re.sub(r"[\s_]+", "-", name)


def _expand_path(path):
    return os.path.expanduser(os.path.expandvars(path))


def _is_executable(path):
    path = _expand_path(path)
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def _flatpak_export_dirs():
    xdg_data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return (
        "/var/lib/flatpak/exports/bin",
        os.path.join(xdg_data, "flatpak/exports/bin"),
    )


def _find_spec_executable(spec):
    """Locate a known browser: PATH command first, then OS paths, then Flatpak exports."""
    for command in spec.get("commands", ()):
        found = shutil.which(command)
        if found:
            return found

    for path in spec.get(_current_os(), ()):
        found = _is_executable(path)
        if found:
            return found

    for app_id in spec.get("flatpak", ()):
        found = shutil.which(app_id)
        if found:
            return found
        for export_dir in _flatpak_export_dirs():
            found = _is_executable(os.path.join(export_dir, app_id))
            if found:
                return found

    return None


def detect_browsers():
    """Return every known browser installed on this machine, in preference order."""
    found = []
    seen_paths = set()
    for spec in BROWSER_SPECS:
        path = _find_spec_executable(spec)
        if not path:
            continue
        real_path = os.path.realpath(path)
        if real_path in seen_paths:
            continue
        seen_paths.add(real_path)
        found.append({
            "key": spec["key"],
            "label": spec["label"],
            "engine": spec["engine"],
            "path": path,
        })
    return found


# Aliases such as "Google Chrome", "google-chrome-stable" and "chrome" all map to a spec.
_BROWSER_ALIASES = {}
for _spec in BROWSER_SPECS:
    for _alias in (_spec["key"], _spec["label"], *_spec["commands"]):
        _BROWSER_ALIASES[_normalize(_alias)] = _spec
del _spec, _alias


def infer_browser_engine(path):
    """Infer the automation engine from an executable name, falling back to --version."""
    name = _normalize(path)

    if any(marker in name for marker in ("firefox", "zen", "librewolf", "waterfox", "floorp", "tor-browser")):
        return FIREFOX
    if "msedge" in name or "microsoft-edge" in name or name == "edge":
        return EDGE
    if any(marker in name for marker in ("chrome", "chromium", "brave", "vivaldi", "opera", "helium")):
        return CHROMIUM

    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_text = (result.stdout + result.stderr).lower()
        if any(marker in version_text for marker in ("firefox", "zen", "librewolf", "waterfox", "floorp", "mozilla")):
            return FIREFOX
        if "edge" in version_text:
            return EDGE
    except Exception:
        pass

    # Unknown executable: the Chromium driver is the safer default.
    return CHROMIUM


def browser_major_version(path):
    """Read the Chromium major version so undetected-chromedriver fetches the right driver."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_text = result.stdout + result.stderr
        match = re.search(r"(?:chromium|chrome)[^0-9]{0,10}(\d+)\.", version_text, re.IGNORECASE)
        if not match:
            match = re.search(r"(\d+)\.\d+\.\d+", version_text)
        return int(match.group(1)) if match else None
    except Exception:
        return None


def resolve_browser(value, detected=None):
    """
    Resolve --browser into {key, label, engine, path}.

    Accepts anything the user could type in a terminal: a command name
    (chromium, helium-browser, brave-browser), a friendly alias (chrome, brave),
    or an absolute path. Returns None for "auto".
    """
    value = (value or "").strip()
    if not value or _normalize(value) in ("auto", "auto-detect", "auto-detect-browser"):
        return None

    path = None
    expanded = _expand_path(value)
    if os.path.isfile(expanded):
        path = expanded
    if not path:
        path = shutil.which(value)

    spec = _BROWSER_ALIASES.get(_normalize(value))

    if not path and spec:
        path = _find_spec_executable(spec)

    if not path and detected:
        for browser in detected:
            if _normalize(browser["label"]) == _normalize(value):
                return browser

    if not path:
        raise BrowserNotFound(value)

    # A command name or path may still match a known spec (e.g. /usr/bin/chromium).
    if spec is None:
        spec = _BROWSER_ALIASES.get(_normalize(path))

    if spec:
        label = spec["label"]
        engine = spec["engine"]
        key = spec["key"]
    else:
        label = os.path.basename(path)
        engine = infer_browser_engine(path)
        key = _normalize(label)

    if engine != CHROMIUM:
        raise BrowserUnsupported(value, label, engine)

    return {"key": key, "label": label, "engine": engine, "path": path}


def format_browser_list(browsers=None):
    browsers = detect_browsers() if browsers is None else browsers
    if not browsers:
        return (
            "No known Chromium-based browsers were detected.\n"
            "Install one, or pass --browser with any command that works in your terminal\n"
            "(e.g. --browser chromium) or a full path."
        )

    lines = ["Detected Chromium-based browsers (Auto-Detect uses the first one):"]
    for browser in browsers:
        lines.append(
            f"  {browser['label']:<20} {browser['engine']:<9} {browser['path']}"
        )
    lines.append("")
    lines.append("Use any of these with --browser, the command name, or a full path.")
    return "\n".join(lines)


class FitgirlExtractorApp:
    def __init__(self, root, preferred_browser=None):
        self.root = root
        self.root.title("FitGirl FF Link Extractor (Pro)")
        self.root.geometry("700x750")
        self.root.minsize(550, 600)
        
        # Configure layout weighting
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1) # Checklist area
        self.root.rowconfigure(5, weight=1) # Output area

        self.browsers = detect_browsers()
        self.preferred_label = None
        if preferred_browser:
            self.preferred_label = self._add_browser(preferred_browser)

        self.checkbox_vars = {}  # Store {url: BooleanVar}
        self.checkbox_list = []
        self.widget_to_index = {}
        self.last_clicked_idx = None
        self.drag_target_val = None
        self.drag_scroll_job = None
        self.last_drag_y = None
        
        # Custom Progress Bar Theme
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(
            "Custom.Horizontal.TProgressbar",
            background="#24890d",
            troughcolor="#e0e0e0",
            bordercolor="#24890d",
            lightcolor="#24890d",
            darkcolor="#24890d"
        )

        self.setup_ui()

        # Bind MouseWheel globally
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Button-4>", self._on_mousewheel) 
        self.root.bind_all("<Button-5>", self._on_mousewheel)
        self.root.bind_all("<ButtonRelease-1>", self._on_mouse_release)

    def _add_browser(self, browser):
        """Add a browser chosen on the command line to the dropdown and return its label."""
        real_path = os.path.realpath(browser["path"])
        for existing in self.browsers:
            if os.path.realpath(existing["path"]) == real_path:
                return existing["label"]

        label = browser["label"]
        if any(existing["label"] == label for existing in self.browsers):
            label = f"{label} ({os.path.basename(browser['path'])})"
            browser = dict(browser, label=label)

        self.browsers.insert(0, browser)
        return label

    def setup_ui(self):
        # 1. Input Frame
        input_frame = ttk.Frame(self.root, padding="10 10 10 5")
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(
            input_frame,
            text="Paste URL / Game URL / HTML or fuckingfast links:",
            font=("Arial", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=5)
        
        self.url_var = tk.StringVar()
        self.url_var.set("https://fitgirl-repacks.site/grand-theft-auto-v/")
        self.url_entry = ttk.Entry(input_frame, textvariable=self.url_var, font=("Arial", 10))
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        
        self.fetch_btn = ttk.Button(input_frame, text="1. Fetch Links", command=self.start_fetch_thread)
        self.fetch_btn.grid(row=2, column=0, columnspan=2, pady=5)

        # 2. Status Label
        self.status_var = tk.StringVar()
        self.status_var.set("Waiting for input...")
        status_label = ttk.Label(self.root, textvariable=self.status_var, font=("Arial", 9, "italic"), foreground="#555")
        status_label.grid(row=1, column=0, sticky="w", padx=10)

        # 3. Checklist Area (Scrollable)
        checklist_container = ttk.LabelFrame(
            self.root,
            text="Found Parts (Click, Shift+Click, or Drag to toggle)",
            padding="5 5 5 5"
        )
        checklist_container.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        checklist_container.rowconfigure(0, weight=1)
        checklist_container.columnconfigure(0, weight=1)

        # Canvas & Scrollbar for Checklist
        self.canvas = tk.Canvas(checklist_container, highlightthickness=0)
        self.scrollbar_list = ttk.Scrollbar(checklist_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar_list.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar_list.grid(row=0, column=1, sticky="ns")

        # Checklist Controls
        controls_frame = ttk.Frame(checklist_container)
        controls_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Button(controls_frame, text="Select All", command=self.select_all).pack(side="left", padx=2)
        ttk.Button(controls_frame, text="Deselect All", command=self.deselect_all).pack(side="left", padx=2)
        
        self.extract_btn = ttk.Button(controls_frame, text="2. Extract Selected", command=self.start_extraction_thread, state="disabled")
        self.extract_btn.pack(side="right", padx=2)
        self.browser_var = tk.StringVar(value="Auto-Detect Browser")
        self.browser_combo = ttk.Combobox(controls_frame, textvariable=self.browser_var, state="readonly", width=22)
        self.browser_combo['values'] = (
            ["Auto-Detect Browser"] + [browser["label"] for browser in self.browsers]
        )
        if self.preferred_label:
            self.browser_var.set(self.preferred_label)
        elif not self.browsers:
            self.browser_var.set("Auto-Detect Browser")
            self.status_var.set(
                "No supported browser found. Install one or launch with --browser NAME (see --list-browsers)."
            )
        self.browser_combo.pack(side="right", padx=(5, 10))

        # 4. Progress Bar
        self.progress = ttk.Progressbar(
            self.root, 
            orient="horizontal", 
            mode="determinate",
            style="Custom.Horizontal.TProgressbar"
        )
        self.progress.grid(row=4, column=0, sticky="ew", padx=10, pady=5)

        # 5. Output Links Frame
        output_frame = ttk.LabelFrame(self.root, text="Extracted Direct Links", padding="5 5 5 5")
        output_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=5)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self.text_area = tk.Text(output_frame, wrap="none", font=("Consolas", 9), height=10)
        self.text_area.grid(row=0, column=0, sticky="nsew")
        
        scrollbar_y = ttk.Scrollbar(output_frame, orient="vertical", command=self.text_area.yview)
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        self.text_area.configure(yscrollcommand=scrollbar_y.set)

        scrollbar_x = ttk.Scrollbar(output_frame, orient="horizontal", command=self.text_area.xview)
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        self.text_area.configure(xscrollcommand=scrollbar_x.set)

        # 6. Bottom Buttons Frame
        btn_frame = ttk.Frame(self.root, padding="10 5 10 10")
        btn_frame.grid(row=6, column=0, sticky="ew")
        
        self.copy_btn = ttk.Button(btn_frame, text="📋 Copy All Links", command=self.copy_to_clipboard)
        self.copy_btn.pack(side="right")
        
        self.clear_btn = ttk.Button(btn_frame, text="Clear Output", command=self.clear_output)
        self.clear_btn.pack(side="right", padx=10)

    # --- Mousewheel & Multi-Select Logic ---

    def _on_mousewheel(self, event):
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if widget == self.canvas or (widget and str(widget).startswith(str(self.scrollable_frame))):
                if hasattr(event, 'delta') and event.delta != 0:
                    direction = -1 if event.delta > 0 else 1
                    self.canvas.yview_scroll(direction, "units")
                elif hasattr(event, 'num'):
                    if event.num == 4:
                        self.canvas.yview_scroll(-1, "units")
                    elif event.num == 5:
                        self.canvas.yview_scroll(1, "units")
        except Exception:
            pass

    def _on_chk_press(self, event, idx):
        """Normal click: toggle this item and set the drag/shift anchor."""
        var, _ = self.checkbox_list[idx]
        new_val = not var.get()
        var.set(new_val)
        self.last_clicked_idx = idx
        self.drag_target_val = new_val
        return "break"

    def _on_chk_shift_press(self, event, idx):
        """Shift+Click: set all checkboxes between the last clicked item and this one."""
        if self.last_clicked_idx is None:
            return self._on_chk_press(event, idx)

        anchor_var, _ = self.checkbox_list[self.last_clicked_idx]
        target_val = anchor_var.get()

        start = min(self.last_clicked_idx, idx)
        end = max(self.last_clicked_idx, idx)
        for i in range(start, end + 1):
            self.checkbox_list[i][0].set(target_val)

        self.last_clicked_idx = idx
        return "break"

    def _on_chk_drag(self, event):
        """Click-and-Drag: paint checkboxes and start auto-scroll near canvas edges."""
        if self.drag_target_val is None:
            return
        self.last_drag_y = event.y_root
        self._paint_drag_to_y(event.y_root)

        if self.drag_scroll_job is None:
            self._auto_scroll_step()

    def _index_at_screen_y(self, y_root):
        """Find the checkbox nearest a screen Y coordinate, clamped to the canvas."""
        if not self.checkbox_list:
            return None

        canvas_top = self.canvas.winfo_rooty()
        canvas_bottom = canvas_top + self.canvas.winfo_height()
        clamped_y = max(canvas_top + 2, min(y_root, canvas_bottom - 2))
        local_y = clamped_y - self.scrollable_frame.winfo_rooty()

        return min(
            range(len(self.checkbox_list)),
            key=lambda i: abs(
                self.checkbox_list[i][1].winfo_y()
                + self.checkbox_list[i][1].winfo_height() / 2
                - local_y
            ),
        )

    def _paint_drag_to_y(self, y_root):
        """Paint checkboxes between the previous and current vertical positions."""
        idx = self._index_at_screen_y(y_root)
        if idx is None:
            return

        if self.last_clicked_idx is not None:
            start = min(self.last_clicked_idx, idx)
            end = max(self.last_clicked_idx, idx)
            for i in range(start, end + 1):
                self.checkbox_list[i][0].set(self.drag_target_val)
        else:
            self.checkbox_list[idx][0].set(self.drag_target_val)
        self.last_clicked_idx = idx

    def _auto_scroll_step(self):
        """Scroll and paint repeatedly while dragging near or beyond canvas edges."""
        self.drag_scroll_job = None
        if self.drag_target_val is None or self.last_drag_y is None:
            return

        canvas_top = self.canvas.winfo_rooty()
        canvas_bottom = canvas_top + self.canvas.winfo_height()
        edge_zone = 25

        step = 0
        if self.last_drag_y < canvas_top + edge_zone:
            dist = (canvas_top + edge_zone) - self.last_drag_y
            step = -max(1, min(4, int(dist // 15) + 1))
        elif self.last_drag_y > canvas_bottom - edge_zone:
            dist = self.last_drag_y - (canvas_bottom - edge_zone)
            step = max(1, min(4, int(dist // 15) + 1))

        if step != 0:
            self.canvas.yview_scroll(step, "units")
            self.root.update_idletasks()
            self._paint_drag_to_y(self.last_drag_y)
            self.drag_scroll_job = self.root.after(35, self._auto_scroll_step)

    def _on_mouse_release(self, event):
        self.drag_target_val = None
        self.last_drag_y = None
        if self.drag_scroll_job is not None:
            self.root.after_cancel(self.drag_scroll_job)
            self.drag_scroll_job = None

    # --- UI Logic ---

    def select_all(self):
        for var in self.checkbox_vars.values():
            var.set(True)

    def deselect_all(self):
        for var in self.checkbox_vars.values():
            var.set(False)

    def copy_to_clipboard(self):
        links = self.text_area.get(1.0, tk.END).strip()
        if links:
            self.root.clipboard_clear()
            self.root.clipboard_append(links)
            messagebox.showinfo("Success", "All links copied to clipboard!")
        else:
            messagebox.showwarning("Empty", "No links to copy!")

    def clear_output(self):
        self.text_area.delete(1.0, tk.END)
        self.progress.config(value=0)

    def update_ui(self, status=None, progress_val=None, max_val=None, text_append=None):
        if status is not None:
            self.status_var.set(status)
        if max_val is not None:
            self.progress.config(maximum=max_val)
        if progress_val is not None:
            self.progress.config(value=progress_val)
        if text_append is not None:
            self.text_area.insert(tk.END, text_append + "\n")
            self.text_area.see(tk.END)

    # --- Step 1: Fetching Links ---

    def start_fetch_thread(self):
        raw = self.url_var.get().strip()
        if not raw:
            messagebox.showerror(
                "Error",
                "Enter a FitGirl paste URL, game page URL, or paste fuckingfast HTML/links.",
            )
            return

        self.fetch_btn.config(state="disabled")
        self.extract_btn.config(state="disabled")
        self.status_var.set("Fetching / decrypting links...")
        
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.checkbox_vars.clear()
        self.checkbox_list.clear()
        self.widget_to_index.clear()
        self.last_clicked_idx = None

        thread = threading.Thread(target=self.run_fetch, args=(raw,), daemon=True)
        thread.start()

    def _links_from_paste_url(self, paste_url):
        paste_text = decrypt_privatebin_paste(paste_url)
        return extract_ff_links(paste_text)

    def _links_from_page_html(self, html):
        links = extract_ff_links(html)
        soup = BeautifulSoup(html, "html.parser")
        paste_urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "paste.fitgirl-repacks.site" in href and "#" in href:
                paste_urls.append(href)
            elif "fuckingfast.co" in href and href not in links:
                links.append(href)
        for match in PASTE_URL_RE.findall(html):
            if match not in paste_urls:
                paste_urls.append(match)
        for paste_url in paste_urls:
            for link in self._links_from_paste_url(paste_url):
                if link not in links:
                    links.append(link)
        return links

    def run_fetch(self, raw):
        try:
            ff_links = []
            non_empty = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            first_line = non_empty[0] if non_empty else ""
            is_single_http_url = (
                len(non_empty) == 1
                and first_line.lower().startswith("http")
                and "<" not in first_line
            )

            # A) PrivateBin paste URL(s) — decrypt client-side AES paste
            paste_urls = PASTE_URL_RE.findall(raw)
            if not paste_urls and is_single_http_url and "paste.fitgirl-repacks.site" in first_line:
                paste_urls = [first_line]
            if paste_urls:
                self.root.after(0, self.update_ui, "Decrypting PrivateBin paste...")
                for paste_url in paste_urls:
                    for link in self._links_from_paste_url(paste_url):
                        if link not in ff_links:
                            ff_links.append(link)

            # B) FitGirl game page — scrape FF links and any nested paste links
            if not ff_links and is_single_http_url and "fuckingfast.co" not in first_line.lower():
                self.root.after(0, self.update_ui, "Fetching game page...")
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                res = requests.get(first_line, headers=headers, timeout=20)
                res.raise_for_status()
                ff_links = self._links_from_page_html(res.text)

            # C) Pasted HTML (<a href="https://fuckingfast.co/...">), markdown, or raw FF URLs
            if not ff_links:
                ff_links = extract_ff_links(raw)

            self.root.after(0, self.populate_checkboxes, ff_links)

        except requests.exceptions.ConnectionError:
            self.root.after(
                0,
                self.update_ui,
                "Network Error: Cannot reach host. Is your ISP blocking it? Try a VPN/Custom DNS.",
            )
            self.root.after(0, lambda: self.fetch_btn.config(state="normal"))
        except Exception as e:
            print(f"FETCH ERROR: {e}")
            self.root.after(0, self.update_ui, f"Error fetching links: {str(e)}")
            self.root.after(0, lambda: self.fetch_btn.config(state="normal"))

    def populate_checkboxes(self, links):
        if not links:
            self.status_var.set("No FuckingFast links found on this page!")
            self.fetch_btn.config(state="normal")
            return

        self.checkbox_list.clear()
        self.widget_to_index.clear()
        self.last_clicked_idx = None
        self.drag_target_val = None

        for idx, link in enumerate(links):
            var = tk.BooleanVar(value=True)
            self.checkbox_vars[link] = var
            
            filename = link.split('#')[-1] if '#' in link else link.split('/')[-1]
            
            chk = ttk.Checkbutton(self.scrollable_frame, text=filename, variable=var)
            chk.pack(anchor="w", padx=5, pady=2)

            self.checkbox_list.append((var, chk))
            self.widget_to_index[chk] = idx

            chk.bind("<ButtonPress-1>", lambda e, i=idx: self._on_chk_press(e, i))
            chk.bind("<Shift-ButtonPress-1>", lambda e, i=idx: self._on_chk_shift_press(e, i))
            chk.bind("<B1-Motion>", self._on_chk_drag)

        self.status_var.set(f"Found {len(links)} parts. (Tip: Shift+Click or Drag to multi-select)")
        self.fetch_btn.config(state="normal")
        self.extract_btn.config(state="normal")

    # --- Step 2: Extraction ---
    def get_selected_browser(self):
        selected_label = self.browser_var.get()
        if selected_label == "Auto-Detect Browser" or not selected_label:
            return self.browsers[0] if self.browsers else None
        for browser in self.browsers:
            if browser["label"] == selected_label:
                return browser
        return None

    def start_extraction_thread(self):
        selected_links = [url for url, var in self.checkbox_vars.items() if var.get()]
        
        if not selected_links:
            messagebox.showwarning("Warning", "No links selected to extract!")
            return

        self.fetch_btn.config(state="disabled")
        self.extract_btn.config(state="disabled")
        self.clear_output()

        thread = threading.Thread(target=self.run_extraction, args=(selected_links,), daemon=True)
        thread.start()

    def run_extraction(self, links):
        driver = None
        total = len(links)
        
        browser = self.get_selected_browser()
        if not browser:
            self.root.after(0, self.update_ui,
                "Error: no supported browser found. Install a browser or launch with "
                "--browser NAME (run with --list-browsers to see what is installed).")
            self.root.after(0, lambda: self.fetch_btn.config(state="normal"))
            self.root.after(0, lambda: self.extract_btn.config(state="normal"))
            return

        browser_executable = browser["path"]
        browser_engine = browser["engine"]
        browser_name = browser["label"]
        print(f"EXTRACTION START: {total} links, browser={browser_name} ({browser_engine}) -> {browser_executable}")
        self.root.after(0, self.update_ui, f"Initializing using {browser_name} to bypass Cloudflare...", 0, total)
        
        def create_driver(version=None):
            opts = uc.ChromeOptions()
            opts.add_argument("--no-first-run")
            opts.add_argument("--no-default-browser-check")
            if not version:
                version = browser_major_version(browser_executable)
            return uc.Chrome(
                options=opts,
                use_subprocess=True,
                browser_executable_path=browser_executable,
                version_main=version
            )
        
        def ensure_window(drv):
            handles = drv.window_handles
            if not handles:
                raise RuntimeError("all browser windows closed")
            try:
                drv.current_window_handle
            except Exception:
                drv.switch_to.window(handles[-1])
            if len(drv.window_handles) < 2:
                try:
                    drv.execute_script("window.open('about:blank','_blank');")
                except Exception:
                    pass

        def session_is_dead(err):
            msg = str(err)
            return any(s in msg for s in (
                "invalid session id",
                "browser has closed",
                "not connected to DevTools",
                "no such window",
                "web view not found",
                "chrome not reachable",
                "unable to connect to renderer",
                "Tried to run command without establishing a connection",
                "Browsing context has been discarded",
                "Failed to decode response from marionette",
            ))

        working_version = None
        try:
            try:
                driver = create_driver()
            except Exception as e:
                print(f"DRIVER CREATE ERROR ({browser_name}): {e}")
                error_msg = str(e)
                if browser_engine == CHROMIUM and "Current browser version is" in error_msg:
                    match = re.search(r"Current browser version is (\d+)", error_msg)
                    if match:
                        correct_version = int(match.group(1))
                        working_version = correct_version
                        self.root.after(0, self.update_ui, f"Auto-fixing ChromeDriver version to v{correct_version}...")
                        driver = create_driver(version=correct_version)
                    else:
                        raise e
                else:
                    raise e

            def extract_one(drv, link, filename):
                ensure_window(drv)
                drv.get(link)

                clicked_widget = False
                for tick in range(60):
                    time.sleep(1)
                    page_html = drv.page_source

                    match_old = re.search(r'window\.open\("([^"]+)"\)', page_html)
                    if match_old:
                        return match_old.group(1)

                    match_new = re.search(r'hx-post="([^"]+)"', page_html)
                    if match_new:
                        turnstile_token = drv.execute_script(
                            "return window.turnstileToken"
                            " || (document.querySelector('[name=\"cf-turnstile-response\"]') || {}).value"
                            " || null;")
                        if not turnstile_token:
                            if 'data-sitekey' in page_html:
                                if not clicked_widget and tick >= 2:
                                    clicked_widget = True
                                    try:
                                        el = drv.find_element(By.ID, "cf-turnstile")
                                        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                                        ActionChains(drv).move_to_element_with_offset(
                                            el, 30 - el.size['width'] // 2, 0).click().perform()
                                    except Exception:
                                        pass
                                if tick == 10:
                                    self.root.after(0, self.update_ui,
                                        "Cloudflare check pending — if a captcha checkbox is visible in the browser window, please click it")
                                continue
                            turnstile_token = ""

                        post_endpoint = match_new.group(1)
                        js_fetch = """
                        var token = arguments[0];
                        var endpoint = arguments[1];
                        var callback = arguments[arguments.length - 1];
                        fetch(endpoint, {
                            method: 'POST',
                            headers: {
                                'HX-Request': 'true',
                                'Content-Type': 'application/x-www-form-urlencoded'
                            },
                            body: 'cf-turnstile-response=' + encodeURIComponent(token)
                        }).then(response => {
                            let redirectUrl = response.headers.get('hx-redirect') || response.headers.get('location');
                            if (redirectUrl) {
                                callback(redirectUrl);
                            } else {
                                response.text().then(t => callback(t));
                            }
                        }).catch(e => callback("ERROR"));
                        """

                        drv.set_script_timeout(10)
                        try:
                            result = drv.execute_async_script(js_fetch, turnstile_token, post_endpoint)
                            if result:
                                if result.startswith("http"):
                                    return result
                                else:
                                    match_url = re.search(r'(https://dl\.fuckingfast\.co/dl/[^\'"]+)', result)
                                    if match_url:
                                        return match_url.group(1)
                        except Exception:
                            pass

                return None

            for i, link in enumerate(links, 1):
                filename = link.split('#')[-1] if '#' in link else link.split('/')[-1]
                self.root.after(0, self.update_ui, f"Processing [{i}/{total}]: {filename}")

                for attempt in range(2):
                    try:
                        direct_url = extract_one(driver, link, filename)
                        if direct_url:
                            self.root.after(0, self.update_ui, None, i, None, direct_url)
                        else:
                            self.root.after(0, self.update_ui, None, i, None, f"# FAILED: {filename} ({link})")
                        break
                    except Exception as e:
                        if attempt == 0 and session_is_dead(e):
                            self.root.after(0, self.update_ui, f"Browser closed — relaunching {browser_name}, retrying [{i}/{total}]...")
                            try:
                                driver.quit()
                            except Exception:
                                pass
                            driver = create_driver(version=working_version)
                            continue
                        self.root.after(0, self.update_ui, None, i, None, f"# ERROR: {str(e)} -> {filename}")
                        break
            else:
                self.root.after(0, self.update_ui, f"Extraction complete! Processed {total} links.")
            
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
            self.root.after(0, self.update_ui, f"Critical Error: {str(e)}")
            
        finally:
            self.root.after(0, lambda: self.fetch_btn.config(state="normal"))
            self.root.after(0, lambda: self.extract_btn.config(state="normal"))
            if driver:
                try:
                    driver.quit()
                except:
                    pass

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="ff_grabber.py",
        description=(
            "Fetch fuckingfast links from FitGirl pages/pastes and resolve direct download URLs. "
            "The GUI opens with the chosen browser preselected."
        ),
    )
    parser.add_argument(
        "-b", "--browser",
        metavar="NAME|PATH",
        help=(
            "Chromium-based browser to use. Accepts anything that works in your terminal "
            "(chromium, helium-browser, brave-browser, google-chrome, vivaldi, opera) "
            "or a full path. Default: auto-detect."
        ),
    )
    parser.add_argument(
        "--list-browsers",
        action="store_true",
        help="List detected browsers and exit.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    detected = detect_browsers()
    if args.list_browsers:
        print(format_browser_list(detected))
        return 0

    preferred_browser = None
    if args.browser:
        try:
            preferred_browser = resolve_browser(args.browser, detected)
        except BrowserNotFound:
            print(f"error: browser '{args.browser}' was not found.", file=sys.stderr)
            print(
                "Pass a command that works in your terminal "
                "(e.g. --browser chromium), a full path, or one of these:\n",
                file=sys.stderr,
            )
            print(format_browser_list(detected), file=sys.stderr)
            return 2
        except BrowserUnsupported as e:
            print(
                f"error: {e.label} is not supported yet. "
                "Only Chromium-based browsers are supported right now "
                "(Chrome, Brave, Chromium, Helium, Vivaldi, Opera).",
                file=sys.stderr,
            )
            print("", file=sys.stderr)
            print(format_browser_list(detected), file=sys.stderr)
            return 2

    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"error: could not open the GUI ({e}). This tool needs a desktop session.", file=sys.stderr)
        return 1

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    app = FitgirlExtractorApp(root, preferred_browser=preferred_browser)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())