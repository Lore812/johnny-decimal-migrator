#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Johnny.Decimal Migrator
========================
Local app (Tkinter, no external dependencies required) to help move and
rename files scattered around your computer into a folder structure
organized with the Johnny.Decimal method.

How it works, in short:
1. You point it to the index file (e.g. "00.00 Index.md") describing the tree.
2. You point it to the "root" folder where the real folder structure already
   lives.
3. You point it to one or more "source" folders full of files to sort.
4. For each file (or folder) the app suggests a destination based on
   keywords/extensions and a new name in the format
   YYYY.MM.DD_Clean_File_Name.
5. You confirm (or correct) and the app renames + moves the item. Every
   move can be undone and is logged to a CSV file.

Run with: python johnny_migrator.py
Requires only Python 3.9+ with Tkinter (included by default on Windows).
"""

import csv
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "migrator_config.json"

# Names/extensions always ignored during scanning
IGNORE_NAMES = {
    "thumbs.db", "desktop.ini", ".ds_store", "migrator_config.json",
    "migration_log.csv", "ignore_list.json",
}
IGNORE_EXT = {".tmp", ".part", ".crdownload"}

# Stopwords used to strip common filler words before matching keywords.
# Includes both Italian and English words, since the index and the files
# being sorted may be in either language regardless of the UI language.
STOPWORDS = {
    # Italian
    "il", "lo", "la", "i", "gli", "le", "di", "a", "da", "in", "con", "su",
    "per", "tra", "fra", "e", "o", "un", "una", "uno", "del", "della",
    "dei", "degli", "delle", "al", "allo", "alla", "ai", "agli", "alle",
    "e-mail", "ed", "che", "come", "più", "meno", "ma", "se", "non",
    # English
    "the", "an", "of", "to", "on", "for", "and", "or", "with", "at",
    "by", "from", "is", "are", "this", "that", "not", "but", "as",
}

STEM_PREFIX_LEN = 5  # very rough stemming: only compares the first N letters
# to match singular/plural forms (e.g. "passport" / "passports")


def stem(word: str) -> str:
    return word[:STEM_PREFIX_LEN] if len(word) > STEM_PREFIX_LEN else word


@dataclass
class QueueItem:
    kind: str  # 'file' or 'folder'
    path: Path


# ---------------------------------------------------------------------------
# Johnny.Decimal index parsing
# ---------------------------------------------------------------------------

@dataclass
class Node:
    text: str
    kind: str  # 'area' | 'category' | 'group' | 'leaf'
    code: str
    title: str
    children: list = field(default_factory=list)
    indent: int = 0


RE_AREA = re.compile(r"^\d{2}-\d{2}\s")
RE_CATEGORY = re.compile(r"^(\d{2})\s+\S")
RE_LEAF_OR_GROUP = re.compile(r"^(\d{2}\.\d{2})\s+(.*)$")


def classify_line(text: str):
    if RE_AREA.match(text):
        return "area", None, text
    m = RE_LEAF_OR_GROUP.match(text)
    if m:
        code, rest = m.group(1), m.group(2)
        kind = "group" if "■" in text else "leaf"
        title = rest.replace("■", "").strip()
        return kind, code, title
    if RE_CATEGORY.match(text) and not re.match(r"^\d{2}\.\d{2}", text):
        code = text.split()[0]
        title = text[len(code):].strip()
        return "category", code, title
    return "unknown", None, text


def recompute_leaf_keywords(leaf):
    """Recomputes from scratch the (stemmed) keywords and extension-keywords
    of a leaf folder, starting from its title/breadcrumb and its saved
    custom words (leaf['custom_words']). A custom word starting with a dot
    (e.g. '.epub') is treated as a direct match on the file extension,
    not as a word in the file name."""
    words = re.findall(r"[a-zà-ü']+", leaf["breadcrumb"].lower())
    leaf["keywords"] = {stem(w) for w in words if w not in STOPWORDS and len(w) > 2}
    leaf["ext_keywords"] = set()
    for w in leaf.get("custom_words", []):
        w = w.strip().lower()
        if not w:
            continue
        if w.startswith("."):
            leaf["ext_keywords"].add(w)
        else:
            leaf["keywords"].add(stem(w))


def apply_custom_keywords(leaves, custom: dict):
    """Applies the user's saved custom keywords to all leaf folders
    (dict: code -> list of words/extensions)."""
    for leaf in leaves:
        leaf["custom_words"] = list(custom.get(leaf["code"], []))
        recompute_leaf_keywords(leaf)


def parse_index(path: Path):
    """Returns (roots, leaves) where leaves is a list of dicts:
    {code, title, breadcrumb, search_text}"""
    lines = path.read_text(encoding="utf-8").splitlines()
    stack = []  # (indent, Node)
    roots = []
    for raw in lines:
        if not raw.strip():
            continue
        expanded = raw.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))
        text = expanded.strip()
        kind, code, title = classify_line(text)
        node = Node(text=text, kind=kind, code=code or "", title=title, indent=indent)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((indent, node))

    leaves = []

    def walk(node: Node, crumb):
        new_crumb = crumb + [node.title if node.kind != "unknown" else node.text]
        if node.kind == "leaf":
            breadcrumb = " / ".join(new_crumb)
            words = re.findall(r"[a-zà-ü']+", breadcrumb.lower())
            words = [w for w in words if w not in STOPWORDS and len(w) > 2]
            leaves.append({
                "code": node.code,
                "title": node.title,
                "breadcrumb": breadcrumb,
                "keywords": {stem(w) for w in words},
                "ext_keywords": set(),
                "custom_words": [],
            })
        for c in node.children:
            walk(c, new_crumb)

    for r in roots:
        walk(r, [])
    return roots, leaves


# ---------------------------------------------------------------------------
# Matching real folders on disk
# ---------------------------------------------------------------------------

RE_FOLDER_CODE = re.compile(r"^(\d{2}\.\d{2})[\s_.\-]")


def summarize_folder(path: Path, cap: int = 5000):
    """Counts files and total size of a folder (with a cap to avoid
    slowdowns on huge trees)."""
    total_size = 0
    count = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            count += 1
            if count > cap:
                return count, total_size, True
            try:
                total_size += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass
    return count, total_size, False


def list_folder_children(path: Path, max_items: int = 300):
    """Lists the top-level contents of a folder (not recursive), to show
    them before deciding the action, without having to open Explorer."""
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return [], False
    capped = len(entries) > max_items
    entries = entries[:max_items]
    lines = []
    for e in entries:
        if e.is_dir():
            try:
                n = sum(1 for _ in e.iterdir())
            except OSError:
                n = "?"
            lines.append(f"📁  {e.name}   ({n} items)")
        else:
            try:
                size_kb = e.stat().st_size / 1024
            except OSError:
                size_kb = 0
            lines.append(f"📄  {e.name}   ({size_kb:,.0f} KB)")
    return lines, capped


def norm_path(p) -> str:
    """Normalizes a path for reliable comparisons: on Windows this
    equalizes case and separator style (/ vs \\), useful because different
    dialog boxes (askdirectory) can return paths with '/' while
    Path.iterdir() returns them with '\\'."""
    return os.path.normcase(os.path.normpath(str(p)))


def find_real_folder_for_code(root: Path, code: str):
    """Recursively searches under root for a folder whose name starts with
    the given code (e.g. '11.11'). Returns the Path or None."""
    if not root.exists():
        return None
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            if d.startswith(code):
                return Path(dirpath) / d
    return None


# ---------------------------------------------------------------------------
# Destination folder suggestion
# ---------------------------------------------------------------------------

def tokenize_filename(name: str):
    base = Path(name).stem
    base = base.replace("_", " ").replace("-", " ").replace(".", " ")
    words = re.findall(r"[a-zà-ü']+", base.lower())
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return {stem(w) for w in words}


def suggest_keyword(file_path: Path, leaves, parent_folder_name: str = ""):
    tokens = tokenize_filename(file_path.name)
    tokens |= tokenize_filename(parent_folder_name)
    ext = file_path.suffix.lower()
    scored = []
    for leaf in leaves:
        score = len(tokens & leaf["keywords"])
        if ext and ext in leaf.get("ext_keywords", set()):
            score += 3  # strong bonus: the extension is a very reliable signal
        if score > 0:
            scored.append((score, leaf))
    scored.sort(key=lambda x: -x[0])
    return [leaf for _, leaf in scored[:5]]


# ---------------------------------------------------------------------------
# Renaming
# ---------------------------------------------------------------------------

def sanitize_clear_name(stem: str) -> str:
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", stem) if p]
    parts = [p if p.isupper() and len(p) <= 4 else p.capitalize() for p in parts]
    return "_".join(parts)


def file_date_str(path: Path, date_source: str) -> str:
    if date_source == "created":
        ts = os.path.getctime(path)
    else:
        ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts).strftime("%Y.%m.%d")


def build_new_name(file_path: Path, date_source: str, clear_name: str, is_dir: bool = False) -> str:
    date_str = file_date_str(file_path, date_source)
    ext = "" if is_dir else file_path.suffix
    return f"{date_str}_{clear_name}{ext}"


def rename_folder_contents(folder: Path, date_source: str):
    """Renames in bulk (recursively) all the files inside a folder, each
    with the prefix of its OWN creation/modification date (not the
    folder's), without touching subfolder names. Used when moving a whole
    folder and wanting to apply the date prefix to its contents too,
    without reviewing it file by file."""
    for dirpath, _, filenames in os.walk(folder):
        for name in filenames:
            if name.lower() in IGNORE_NAMES:
                continue
            p = Path(dirpath) / name
            if p.suffix.lower() in IGNORE_EXT:
                continue
            try:
                date_str = file_date_str(p, date_source)
            except OSError:
                continue
            clear = sanitize_clear_name(p.stem)
            new_name = f"{date_str}_{clear}{p.suffix}"
            if new_name == p.name:
                continue
            new_path = p.with_name(new_name)
            if new_path.exists():
                stem2, ext2 = os.path.splitext(new_name)
                i = 2
                while (p.parent / f"{stem2}_{i}{ext2}").exists():
                    i += 1
                new_path = p.parent / f"{stem2}_{i}{ext2}"
            try:
                p.rename(new_path)
            except OSError:
                pass  # if a file can't be renamed, keep going with the others


# ---------------------------------------------------------------------------
# Persistent config
# ---------------------------------------------------------------------------

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "index_path": "",
        "root_path": "",
        "source_paths": [],
        "recursive": True,
        "include_folders": True,
        "date_source": "modified",
        "ignore_list": [],
        "excluded_paths": [],
        "custom_keywords": {},
    }


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Log / undo
# ---------------------------------------------------------------------------

def log_action(root: Path, original: Path, destination: Path):
    log_path = root / "migration_log.csv"
    is_new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "original", "destination"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), str(original), str(destination)])


# ---------------------------------------------------------------------------
# Opening files/folders and Recycle Bin (Windows)
# ---------------------------------------------------------------------------

def open_file(path: Path):
    """Opens the file with the Windows default app."""
    os.startfile(str(path))  # Windows only


def open_containing_folder(path: Path):
    """Opens File Explorer in the file's folder, with the file selected."""
    subprocess.run(["explorer", "/select,", str(path)])


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


_FO_DELETE = 3
_FOF_ALLOWUNDO = 0x0040
_FOF_NOCONFIRMATION = 0x0010
_FOF_SILENT = 0x0004


def send_to_recycle_bin(path: Path) -> bool:
    """Moves the file to the Windows Recycle Bin (recoverable), using the
    SHFileOperationW system API. Returns True on success."""
    if sys.platform != "win32":
        raise OSError("The system Recycle Bin is only supported on Windows.")
    # pFrom must be a string terminated by TWO null characters
    buf = ctypes.create_unicode_buffer(str(path.resolve()) + "\0")
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = _FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.pTo = None
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return result == 0 and not op.fAnyOperationsAborted


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class MigratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Johnny.Decimal Migrator")
        self.geometry("1000x720")
        self.minsize(920, 660)

        self.cfg = load_config()
        self.leaves = []
        self.queue = []  # list of items to process
        self.current_index = 0
        self.undo_stack = []  # (original_path, new_path)
        self.ignore_ext_session = set()
        self._current_suggestions = []

        self._build_setup_frame()
        self._build_review_frame()
        self._bind_shortcuts()
        self._show_setup()

    # ---------------- Setup screen ----------------

    def _build_setup_frame(self):
        f = ttk.Frame(self, padding=16)
        self.setup_frame = f

        ttk.Label(f, text="Settings", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        # Index file
        ttk.Label(f, text="Index file (e.g. 00.00 Index.md):").grid(row=1, column=0, sticky="w")
        self.index_var = tk.StringVar(value=self.cfg.get("index_path", ""))
        ttk.Entry(f, textvariable=self.index_var, width=70).grid(row=1, column=1, sticky="we", padx=6)
        ttk.Button(f, text="Browse...", command=self._pick_index).grid(row=1, column=2)

        # Root folder
        ttk.Label(f, text="Organized root folder:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.root_var = tk.StringVar(value=self.cfg.get("root_path", ""))
        ttk.Entry(f, textvariable=self.root_var, width=70).grid(row=2, column=1, sticky="we", padx=6, pady=(8, 0))
        ttk.Button(f, text="Browse...", command=self._pick_root).grid(row=2, column=2, pady=(8, 0))

        # Source folders
        ttk.Label(f, text="Source folders (files to sort):").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        self.source_listbox = tk.Listbox(f, height=5, width=70)
        for p in self.cfg.get("source_paths", []):
            self.source_listbox.insert(tk.END, p)
        self.source_listbox.grid(row=3, column=1, sticky="we", padx=6, pady=(8, 0))
        btns = ttk.Frame(f)
        btns.grid(row=3, column=2, sticky="n", pady=(8, 0))
        ttk.Button(btns, text="Add...", command=self._add_source).pack(fill="x")
        ttk.Button(btns, text="Remove selected", command=self._remove_source).pack(fill="x", pady=(4, 0))

        checks_frame = ttk.Frame(f)
        checks_frame.grid(row=4, column=1, sticky="w", pady=(8, 0))
        self.recursive_var = tk.BooleanVar(value=self.cfg.get("recursive", True))
        ttk.Checkbutton(checks_frame, text="Search inside source subfolders",
                         variable=self.recursive_var).pack(anchor="w")
        self.include_folders_var = tk.BooleanVar(value=self.cfg.get("include_folders", True))
        ttk.Checkbutton(checks_frame,
                         text="Show subfolders as whole blocks (movable/trashable all together)",
                         variable=self.include_folders_var).pack(anchor="w")

        ttk.Label(f, text="Date to use for the prefix:").grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.date_source_var = tk.StringVar(value=self.cfg.get("date_source", "modified"))
        ttk.Combobox(f, textvariable=self.date_source_var, values=["modified", "created"],
                     state="readonly", width=20).grid(row=5, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Separator(f).grid(row=6, column=0, columnspan=3, sticky="we", pady=12)

        # Excluded folders
        ttk.Label(f, text="Folders to exclude from scanning:").grid(row=7, column=0, sticky="nw")
        self.excluded_listbox = tk.Listbox(f, height=4, width=70)
        for p in self.cfg.get("excluded_paths", []):
            self.excluded_listbox.insert(tk.END, p)
        self.excluded_listbox.grid(row=7, column=1, sticky="we", padx=6)
        excl_btns = ttk.Frame(f)
        excl_btns.grid(row=7, column=2, sticky="n")
        ttk.Button(excl_btns, text="Add...", command=self._add_excluded).pack(fill="x")
        ttk.Button(excl_btns, text="Remove selected", command=self._remove_excluded).pack(fill="x", pady=(4, 0))
        ttk.Label(f, text=("Subfolders to skip upfront."),
                  wraplength=880, foreground="#555").grid(row=8, column=1, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Separator(f).grid(row=9, column=0, columnspan=3, sticky="we", pady=12)

        ignore_row = ttk.Frame(f)
        ignore_row.grid(row=10, column=0, columnspan=3, sticky="w")
        self.ignore_count_label = ttk.Label(ignore_row, text="")
        self.ignore_count_label.pack(side="left")
        ttk.Button(ignore_row, text="Reset permanent exclusions",
                   command=self._reset_ignore_list).pack(side="left", padx=(10, 0))
        ttk.Button(ignore_row, text="🔑 Manage suggestion keywords",
                   command=self._open_keyword_manager).pack(side="left", padx=(10, 0))
        self._refresh_ignore_count()

        self.status_label = ttk.Label(f, text="", foreground="#a00")
        self.status_label.grid(row=11, column=0, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Button(f, text="Save and scan  ▶", command=self._start_scan).grid(
            row=12, column=0, columnspan=3, sticky="e", pady=(12, 0))

        f.columnconfigure(1, weight=1)

    def _add_excluded(self):
        path = filedialog.askdirectory(title="Add a folder to exclude from scanning")
        if path:
            self.excluded_listbox.insert(tk.END, path)

    def _remove_excluded(self):
        sel = list(self.excluded_listbox.curselection())
        sel.reverse()
        for i in sel:
            self.excluded_listbox.delete(i)

    def _refresh_ignore_count(self):
        n = len(self.cfg.get("ignore_list", []))
        self.ignore_count_label.config(
            text=f"Files permanently excluded so far: {n}" if n else "No files permanently excluded.")

    def _reset_ignore_list(self):
        n = len(self.cfg.get("ignore_list", []))
        if n == 0:
            return
        if messagebox.askyesno("Reset?", f"Remove {n} exclusions? They will show up again in future scans."):
            self.cfg["ignore_list"] = []
            save_config(self.cfg)
            self._refresh_ignore_count()

    def _ensure_leaves_loaded(self) -> bool:
        if self.leaves:
            return True
        index_path = Path(self.index_var.get().strip())
        if not index_path.is_file():
            messagebox.showwarning("Missing index file", "Select the index file first (above).")
            return False
        try:
            _, self.leaves = parse_index(index_path)
        except Exception as e:
            messagebox.showerror("Error reading the index", str(e))
            return False
        apply_custom_keywords(self.leaves, self.cfg.get("custom_keywords", {}))
        return bool(self.leaves)

    def _open_keyword_manager(self):
        if not self._ensure_leaves_loaded():
            return

        win = tk.Toplevel(self)
        win.title("Manage suggestion keywords")
        win.geometry("760x520")
        win.transient(self)

        main = ttk.Frame(win, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Search for a folder:").pack(anchor="w")
        search_var = tk.StringVar()
        ttk.Entry(main, textvariable=search_var).pack(fill="x", pady=(2, 8))

        body = ttk.Frame(main)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        leaf_list = tk.Listbox(left)
        leaf_scroll = ttk.Scrollbar(left, orient="vertical", command=leaf_list.yview)
        leaf_list.configure(yscrollcommand=leaf_scroll.set)
        leaf_list.pack(side="left", fill="both", expand=True)
        leaf_scroll.pack(side="right", fill="y")

        right = ttk.LabelFrame(body, text="Custom keywords", padding=10)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        selected_label = ttk.Label(right, text="Select a folder on the left", foreground="#555",
                                    wraplength=320)
        selected_label.pack(anchor="w")

        auto_label = ttk.Label(right, text="", foreground="#888", wraplength=320)
        auto_label.pack(anchor="w", pady=(4, 8))

        words_list = tk.Listbox(right, height=10)
        words_list.pack(fill="both", expand=True)

        add_row = ttk.Frame(right)
        add_row.pack(fill="x", pady=(8, 0))
        new_word_var = tk.StringVar()
        new_word_entry = ttk.Entry(add_row, textvariable=new_word_var)
        new_word_entry.pack(side="left", fill="x", expand=True)
        ttk.Label(right, text="Tip: a word starting with a dot (e.g. .epub) "
                              "is recognized as a file extension, not as a word in the name.",
                  foreground="#888", wraplength=320).pack(anchor="w", pady=(4, 0))

        visible_leaves = []
        current_leaf = {"leaf": None}

        def refresh_leaf_list():
            query = search_var.get().lower().strip()
            leaf_list.delete(0, tk.END)
            visible_leaves.clear()
            for leaf in self.leaves:
                if not query or query in leaf["breadcrumb"].lower() or query in leaf["code"].lower():
                    tag = "  🔑" if leaf.get("custom_words") else ""
                    leaf_list.insert(tk.END, f"{leaf['code']}  {leaf['breadcrumb']}{tag}")
                    visible_leaves.append(leaf)

        def show_leaf_words(leaf):
            current_leaf["leaf"] = leaf
            selected_label.config(text=f"{leaf['code']} — {leaf['breadcrumb']}", foreground="#0a6")
            auto_title_words = sorted({w for w in re.findall(r"[a-zà-ü']+", leaf["title"].lower())
                                        if w not in STOPWORDS and len(w) > 2})
            auto_label.config(text="Words already used automatically (from the title): "
                                    + (", ".join(auto_title_words) if auto_title_words else "none"))
            words_list.delete(0, tk.END)
            for w in leaf.get("custom_words", []):
                words_list.insert(tk.END, w)

        def on_select(event=None):
            sel = leaf_list.curselection()
            if not sel:
                return
            show_leaf_words(visible_leaves[sel[0]])

        def persist_current():
            leaf = current_leaf["leaf"]
            if leaf is None:
                return
            words = list(words_list.get(0, tk.END))
            leaf["custom_words"] = words
            custom = self.cfg.setdefault("custom_keywords", {})
            if words:
                custom[leaf["code"]] = words
            else:
                custom.pop(leaf["code"], None)
            save_config(self.cfg)
            recompute_leaf_keywords(leaf)
            refresh_leaf_list()

        def add_word(event=None):
            w = new_word_var.get().strip().lower()
            if not w or current_leaf["leaf"] is None:
                return
            existing = list(words_list.get(0, tk.END))
            if w not in existing:
                words_list.insert(tk.END, w)
                persist_current()
            new_word_var.set("")

        def remove_selected_word():
            sel = words_list.curselection()
            if not sel or current_leaf["leaf"] is None:
                return
            for i in reversed(sel):
                words_list.delete(i)
            persist_current()

        ttk.Button(add_row, text="Add", command=add_word).pack(side="left", padx=(6, 0))
        new_word_entry.bind("<Return>", add_word)
        ttk.Button(right, text="Remove selected", command=remove_selected_word).pack(anchor="w", pady=(6, 0))

        search_var.trace_add("write", lambda *a: refresh_leaf_list())
        leaf_list.bind("<<ListboxSelect>>", on_select)

        refresh_leaf_list()

    def _pick_index(self):
        path = filedialog.askopenfilename(title="Select the index file",
                                           filetypes=[("Markdown/Text", "*.md *.txt"), ("All files", "*.*")])
        if path:
            self.index_var.set(path)

    def _pick_root(self):
        path = filedialog.askdirectory(title="Select the organized root folder")
        if path:
            self.root_var.set(path)

    def _add_source(self):
        path = filedialog.askdirectory(title="Add a source folder")
        if path:
            self.source_listbox.insert(tk.END, path)

    def _remove_source(self):
        sel = list(self.source_listbox.curselection())
        sel.reverse()
        for i in sel:
            self.source_listbox.delete(i)

    def _start_scan(self):
        index_path = Path(self.index_var.get().strip())
        root_path = Path(self.root_var.get().strip())
        sources = [Path(self.source_listbox.get(i)) for i in range(self.source_listbox.size())]

        if not index_path.is_file():
            self.status_label.config(text="⚠ Select a valid index file.")
            return
        if not root_path.is_dir():
            self.status_label.config(text="⚠ Select a valid root folder.")
            return
        if not sources:
            self.status_label.config(text="⚠ Add at least one source folder.")
            return

        excluded = [self.excluded_listbox.get(i) for i in range(self.excluded_listbox.size())]

        self.cfg.update({
            "index_path": str(index_path),
            "root_path": str(root_path),
            "source_paths": [str(s) for s in sources],
            "recursive": self.recursive_var.get(),
            "include_folders": self.include_folders_var.get(),
            "date_source": self.date_source_var.get(),
            "excluded_paths": excluded,
        })
        save_config(self.cfg)

        try:
            _, self.leaves = parse_index(index_path)
        except Exception as e:
            self.status_label.config(text=f"⚠ Error reading the index: {e}")
            return

        if not self.leaves:
            self.status_label.config(text="⚠ No leaf folders found in the index.")
            return

        apply_custom_keywords(self.leaves, self.cfg.get("custom_keywords", {}))

        self.root_path = root_path
        self.queue = self._scan_sources(sources, self.recursive_var.get(), self.include_folders_var.get())
        self.current_index = 0

        if not self.queue:
            messagebox.showinfo("Done", "No files found in the specified source folders.")
            return

        self._show_review()
        self._load_current_file()

    def _scan_sources(self, sources, recursive, include_folders):
        ignore_set = {norm_path(p) for p in self.cfg.get("ignore_list", [])} | \
                     {norm_path(p) for p in self.cfg.get("excluded_paths", [])}
        items = []

        def walk_dir(d: Path):
            try:
                entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for entry in entries:
                if entry.name.lower() in IGNORE_NAMES:
                    continue
                if norm_path(entry) in ignore_set:
                    continue
                if entry.is_dir():
                    if include_folders:
                        items.append(QueueItem("folder", entry))
                    if recursive:
                        walk_dir(entry)
                else:
                    if entry.suffix.lower() in IGNORE_EXT:
                        continue
                    items.append(QueueItem("file", entry))

        for src in sources:
            if src.is_dir():
                walk_dir(src)
        return items

    # ---------------- Review screen ----------------

    def _build_review_frame(self):
        f = ttk.Frame(self, padding=10)
        self.review_frame = f

        top = ttk.Frame(f)
        top.pack(fill="x")
        self.progress_label = ttk.Label(top, text="", font=("Segoe UI", 10))
        self.progress_label.pack(side="left")
        ttk.Button(top, text="⚙ Settings", command=self._show_setup).pack(side="right")
        ttk.Button(top, text="↩ Undo last action  [Ctrl+Z]", command=self._undo_last).pack(side="right", padx=(0, 8))

        card = ttk.LabelFrame(f, text="Current item", padding=8)
        card.pack(fill="x", pady=(8, 8))

        self.file_name_label = ttk.Label(card, text="", font=("Segoe UI", 12, "bold"))
        self.file_name_label.pack(anchor="w")
        self.file_meta_label = ttk.Label(card, text="", foreground="#555")
        self.file_meta_label.pack(anchor="w", pady=(2, 0))

        peek_frame = ttk.Frame(card)
        peek_frame.pack(anchor="w", pady=(4, 0))
        ttk.Button(peek_frame, text="👁 Open file  [Ctrl+O]", command=self._open_current_file).pack(side="left")
        ttk.Button(peek_frame, text="📂 Open folder  [Ctrl+L]", command=self._open_current_folder).pack(
            side="left", padx=(6, 0))

        self.contents_frame = ttk.Frame(card)
        ttk.Label(self.contents_frame, text="Folder contents:",
                  foreground="#555").pack(anchor="w", pady=(6, 2))
        contents_inner = ttk.Frame(self.contents_frame)
        contents_inner.pack(fill="both", expand=True)
        self.contents_listbox = tk.Listbox(contents_inner, height=4)
        contents_scroll = ttk.Scrollbar(contents_inner, orient="vertical", command=self.contents_listbox.yview)
        self.contents_listbox.configure(yscrollcommand=contents_scroll.set)
        self.contents_listbox.pack(side="left", fill="both", expand=True)
        contents_scroll.pack(side="right", fill="y")
        self.contents_cap_label = ttk.Label(self.contents_frame, text="", foreground="#a70")
        self.contents_cap_label.pack(anchor="w")
        self.rename_inner_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.contents_frame,
                         text="Rename inner files with their own date prefix ",
                         variable=self.rename_inner_var).pack(anchor="w", pady=(2, 0))
        # not packed by default: shown only for folder items

        name_frame = ttk.Frame(card)
        name_frame.pack(fill="x", pady=(6, 0))
        ttk.Label(name_frame, text="Clean name:").grid(row=0, column=0, sticky="w")
        self.clear_name_var = tk.StringVar()
        self.clear_name_var.trace_add("write", lambda *a: self._update_preview())
        ttk.Entry(name_frame, textvariable=self.clear_name_var, width=50).grid(row=0, column=1, sticky="we", padx=6)
        name_frame.columnconfigure(1, weight=1)
        self.preview_label = ttk.Label(card, text="", foreground="#0a6")
        self.preview_label.pack(anchor="w", pady=(2, 0))

        dest_frame = ttk.LabelFrame(f, text="Destination folder", padding=8)
        dest_frame.pack(fill="both", expand=True)

        sugg_frame = ttk.Frame(dest_frame)
        sugg_frame.pack(fill="x")
        ttk.Label(sugg_frame, text="Suggestions:").pack(anchor="w")
        self.suggestion_buttons_frame = ttk.Frame(sugg_frame)
        self.suggestion_buttons_frame.pack(fill="x", pady=(2, 4))

        ttk.Label(dest_frame, text="Or search manually:  (Ctrl+F for quick focus)").pack(anchor="w")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._refresh_leaf_list())
        self.filter_entry = ttk.Entry(dest_frame, textvariable=self.filter_var)
        self.filter_entry.pack(fill="x", pady=(2, 2))

        list_frame = ttk.Frame(dest_frame)
        list_frame.pack(fill="both", expand=True)
        self.leaf_listbox = tk.Listbox(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.leaf_listbox.yview)
        self.leaf_listbox.configure(yscrollcommand=scrollbar.set)
        self.leaf_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.leaf_listbox.bind("<<ListboxSelect>>", lambda e: self._on_leaf_select())

        self.selected_leaf_label = ttk.Label(dest_frame, text="No folder selected",
                                              foreground="#a00")
        self.selected_leaf_label.pack(anchor="w", pady=(6, 0))

        action_frame = ttk.Frame(f)
        action_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(action_frame, text="Skip ⏭ (for now)  [Ctrl+→]", command=self._skip_current).pack(side="left")
        ttk.Button(action_frame, text="🚫 Never include  [Ctrl+I]",
                   command=self._ignore_forever_current).pack(side="left", padx=(8, 0))
        ttk.Button(action_frame, text="🗑 Send to Recycle Bin  [Ctrl+Del]", command=self._trash_current).pack(side="left", padx=(8, 0))
        ttk.Button(action_frame, text="Move ✔  [Enter]", command=self._move_current).pack(side="right")

        self.selected_leaf = None

    def _in_review(self) -> bool:
        return bool(self.review_frame.winfo_ismapped() and self.queue and
                    self.current_index < len(self.queue))

    def _bind_shortcuts(self):
        # All the combinations deliberately use a modifier key (Ctrl/Enter),
        # so they never interfere with normal typing in text fields.
        def guarded(handler):
            def inner(event=None):
                if self._in_review():
                    handler()
                return "break"
            return inner

        self.bind_all("<Return>", guarded(self._move_current))
        self.bind_all("<Control-Right>", guarded(self._skip_current))
        self.bind_all("<Control-i>", guarded(self._ignore_forever_current))
        self.bind_all("<Control-I>", guarded(self._ignore_forever_current))
        self.bind_all("<Control-Delete>", guarded(self._trash_current))
        self.bind_all("<Control-z>", guarded(self._undo_last))
        self.bind_all("<Control-Z>", guarded(self._undo_last))
        self.bind_all("<Control-o>", guarded(self._open_current_file))
        self.bind_all("<Control-O>", guarded(self._open_current_file))
        self.bind_all("<Control-l>", guarded(self._open_current_folder))
        self.bind_all("<Control-L>", guarded(self._open_current_folder))
        self.bind_all("<Control-f>", guarded(lambda: self.filter_entry.focus_set()))
        self.bind_all("<Control-F>", guarded(lambda: self.filter_entry.focus_set()))
        for i in (1, 2, 3):
            self.bind_all(f"<Control-Key-{i}>", guarded(lambda i=i: self._select_suggestion_by_index(i)))

    def _select_suggestion_by_index(self, i: int):
        idx = i - 1
        if 0 <= idx < len(self._current_suggestions):
            self._select_leaf(self._current_suggestions[idx])

    def _show_setup(self):
        self.review_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True)
        self._refresh_ignore_count()

    def _show_review(self):
        self.setup_frame.pack_forget()
        self.review_frame.pack(fill="both", expand=True)

    def _refresh_leaf_list(self):
        query = self.filter_var.get().lower().strip()
        self.leaf_listbox.delete(0, tk.END)
        self._visible_leaves = []
        for leaf in self.leaves:
            if not query or query in leaf["breadcrumb"].lower() or query in leaf["code"].lower():
                self.leaf_listbox.insert(tk.END, f"{leaf['code']}  {leaf['breadcrumb']}")
                self._visible_leaves.append(leaf)

    def _on_leaf_select(self):
        sel = self.leaf_listbox.curselection()
        if not sel:
            return
        leaf = self._visible_leaves[sel[0]]
        self._select_leaf(leaf)

    def _select_leaf(self, leaf):
        self.selected_leaf = leaf
        self.selected_leaf_label.config(
            text=f"Selected: {leaf['code']} — {leaf['breadcrumb']}", foreground="#0a6")

    def _load_current_file(self):
        if self.current_index >= len(self.queue):
            messagebox.showinfo("Done", "All items have been processed!")
            self._show_setup()
            return

        item = self.queue[self.current_index]
        path = item.path
        is_folder = item.kind == "folder"
        self.progress_label.config(
            text=f"Item {self.current_index + 1} of {len(self.queue)}   —   remaining: {len(self.queue) - self.current_index - 1}")
        icon = "📁" if is_folder else "📄"
        self.file_name_label.config(text=f"{icon} {path.name}")

        if is_folder:
            count, size_bytes, capped = summarize_folder(path)
            size_kb = size_bytes / 1024
            count_text = f"{count}{'+' if capped else ''} files inside"
        else:
            try:
                size_kb = path.stat().st_size / 1024
            except OSError:
                size_kb = 0
            count_text = None
        try:
            c_date = datetime.fromtimestamp(os.path.getctime(path)).strftime("%d/%m/%Y")
            m_date = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d/%m/%Y")
        except OSError:
            c_date = m_date = "?"
        meta_bits = [f"{size_kb:,.0f} KB"]
        if count_text:
            meta_bits.append(count_text)
        meta_bits += [f"created {c_date}", f"modified {m_date}", str(path.parent)]
        self.file_meta_label.config(text="  ·  ".join(meta_bits))

        if is_folder:
            lines, capped = list_folder_children(path)
            self.contents_listbox.delete(0, tk.END)
            for line in lines:
                self.contents_listbox.insert(tk.END, line)
            self.contents_cap_label.config(
                text=f"(showing the first {len(lines)} items, there are more)" if capped else "")
            self.contents_frame.pack(fill="both", expand=True, pady=(0, 4))
        else:
            self.contents_frame.pack_forget()
        self.clear_name_var.set(sanitize_clear_name(path.name if is_folder else path.stem))
        self.selected_leaf = None
        self.selected_leaf_label.config(text="No folder selected", foreground="#a00")
        self.filter_var.set("")
        self._refresh_leaf_list()

        for w in self.suggestion_buttons_frame.winfo_children():
            w.destroy()

        parent_name = path.parent.name
        suggestions = suggest_keyword(path, self.leaves, parent_name)
        self._show_suggestions(suggestions)
        self._update_preview()

    def _show_suggestions(self, suggestions):
        for w in self.suggestion_buttons_frame.winfo_children():
            w.destroy()
        self._current_suggestions = suggestions[:3] if suggestions else []
        if not self._current_suggestions:
            ttk.Label(self.suggestion_buttons_frame,
                      text="No automatic suggestion: search manually below.",
                      foreground="#777").pack(anchor="w")
            return
        for i, leaf in enumerate(self._current_suggestions, start=1):
            b = ttk.Button(self.suggestion_buttons_frame,
                            text=f"[Ctrl+{i}]  {leaf['code']}  {leaf['title']}",
                            command=lambda l=leaf: self._select_leaf(l))
            b.pack(side="left", padx=(0, 6))

    def _update_preview(self):
        if self.current_index >= len(self.queue):
            return
        item = self.queue[self.current_index]
        clear = self.clear_name_var.get().strip() or "NO_NAME"
        try:
            new_name = build_new_name(item.path, self.date_source_var.get(), clear, is_dir=(item.kind == "folder"))
        except OSError:
            new_name = "?"
        self.preview_label.config(text=f"New name: {new_name}")

    def _open_current_file(self):
        item = self.queue[self.current_index]
        try:
            open_file(item.path)
        except Exception as e:
            messagebox.showerror("Unable to open", str(e))

    def _open_current_folder(self):
        item = self.queue[self.current_index]
        try:
            open_containing_folder(item.path)
        except Exception as e:
            messagebox.showerror("Unable to open the folder", str(e))

    def _remove_item_and_descendants(self, target_path: Path):
        """Removes the item at target_path from the queue and, if it's a
        folder, also every item already in the queue that lived inside it
        (whose paths no longer exist after the move/trash)."""
        target = str(target_path)
        prefix = target + os.sep
        removed_before_current = 0
        kept = []
        for i, it in enumerate(self.queue):
            s = str(it.path)
            if s == target or s.startswith(prefix):
                if i < self.current_index:
                    removed_before_current += 1
                continue
            kept.append(it)
        self.queue = kept
        self.current_index -= removed_before_current

    def _trash_current(self):
        item = self.queue[self.current_index]
        path = item.path
        what = "folder (with all its contents)" if item.kind == "folder" else "file"
        if not messagebox.askyesno(
                "Send to Recycle Bin?",
                f"'{path.name}' ({what}) will be moved to the Windows Recycle Bin.\n\n"
                "You'll be able to recover it from there like any other deleted "
                "item, until you empty the Recycle Bin.\n\nContinue?"):
            return
        try:
            ok = send_to_recycle_bin(path)
        except Exception as e:
            messagebox.showerror("Error", f"Unable to send to Recycle Bin:\n{e}")
            return
        if not ok:
            messagebox.showerror("Error", "Operation cancelled or failed.")
            return
        self._remove_item_and_descendants(path)
        self._load_current_file()

    def _skip_current(self):
        self.current_index += 1
        self._load_current_file()

    def _ignore_forever_current(self):
        item = self.queue[self.current_index]
        path = item.path
        what = "the folder (and all its contents)" if item.kind == "folder" else "the file"
        if not messagebox.askyesno(
                "Exclude forever?",
                f"'{path.name}': {what} will no longer be proposed in future scans "
                "of any source folder.\n\n"
                "It is not touched or deleted: it stays where it is, "
                "the app will just stop flagging it to you.\n\n"
                "Continue?"):
            return
        ignore_list = self.cfg.setdefault("ignore_list", [])
        if str(path) not in ignore_list:
            ignore_list.append(str(path))
            save_config(self.cfg)
        # also remove any other occurrences/descendants from the current queue
        self._remove_item_and_descendants(path)
        self._load_current_file()

    def _move_current(self):
        if self.selected_leaf is None:
            messagebox.showwarning("Missing destination", "Select a destination folder first.")
            return
        item = self.queue[self.current_index]
        path = item.path
        is_folder = item.kind == "folder"
        clear = self.clear_name_var.get().strip() or "NO_NAME"
        new_name = build_new_name(path, self.date_source_var.get(), clear, is_dir=is_folder)

        dest_folder = find_real_folder_for_code(self.root_path, self.selected_leaf["code"])
        if dest_folder is None:
            if messagebox.askyesno(
                    "Folder not found",
                    f"The folder '{self.selected_leaf['code']} {self.selected_leaf['title']}' "
                    "doesn't exist on disk inside the specified root yet.\n\n"
                    "Do you want to create it now (named 'CODE Title')? "
                    "Remember: only create folders already planned in the index."):
                dest_folder = self.root_path / f"{self.selected_leaf['code']} {self.selected_leaf['title']}"
                dest_folder.mkdir(parents=True, exist_ok=True)
            else:
                return

        dest_path = dest_folder / new_name
        if dest_path.exists():
            stem, ext = os.path.splitext(new_name)
            i = 2
            while (dest_folder / f"{stem}_{i}{ext}").exists():
                i += 1
            dest_path = dest_folder / f"{stem}_{i}{ext}"

        try:
            shutil.move(str(path), str(dest_path))
        except Exception as e:
            what = "the folder" if is_folder else "the file"
            messagebox.showerror("Error", f"Unable to move {what}:\n{e}")
            return

        log_action(self.root_path, path, dest_path)
        self.undo_stack.append((path, dest_path, item.kind))

        if is_folder:
            if self.rename_inner_var.get():
                try:
                    rename_folder_contents(dest_path, self.date_source_var.get())
                except Exception as e:
                    messagebox.showwarning(
                        "Incomplete inner rename",
                        f"The folder was moved, but some files inside it "
                        f"were not renamed:\n{e}")
            self._remove_item_and_descendants(path)
        else:
            self.current_index += 1
        self._load_current_file()

    def _undo_last(self):
        if not self.undo_stack:
            messagebox.showinfo("Nothing to undo", "There are no recent actions to undo.")
            return
        original, moved, kind = self.undo_stack.pop()
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(moved), str(original))
        except Exception as e:
            messagebox.showerror("Error", f"Unable to undo the move:\n{e}")
            return
        # Put the item back at the top of the current queue
        self.queue.insert(self.current_index, QueueItem(kind, original))
        messagebox.showinfo("Undone", f"Restored: {original.name}")
        self._load_current_file()


if __name__ == "__main__":
    app = MigratorApp()
    app.mainloop()
