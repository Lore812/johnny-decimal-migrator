# Johnny.Decimal Migrator

Local desktop app with a graphical interface to help you sort files
scattered around your computer into a folder structure organized with the
[Johnny.Decimal](https://johnnydecimal.com/) method.

It reads a plain text index file describing your folder tree (see the "How the index is read" section below), and for each file or folder to sort it suggests a destination, a clean name with a date prefix, and leaves the final confirmation to you.

## Requirements

- **Python 3.9 or later** on Windows. If you don't have it yet:
  1. Go to https://www.python.org/downloads/
  2. Download and install the latest version.
  3. **Important**: on the installer's first screen, check the "Add
     python.exe to PATH" box before clicking "Install Now".
- No extra libraries to install: the app only uses Tkinter, included by
  default with the official Python installer for Windows.
- Windows only (it uses Windows system APIs for the Recycle Bin and File
  Explorer). The app will still start on other operating systems, but the
  "Open folder" and "Send to Recycle Bin" buttons won't work.

## How to start it

### Easy method

1. Copy the `johnny_migrator.py` file into any folder.
2. Right-click it and choose `Open with > Python`.

If Python isn't in the list of apps, that depends on how Python was
installed — use the standard method below instead.

### Standard method

1. Copy the `johnny_migrator.py` file into any folder.
2. Open the "Command Prompt" (search "cmd" in the Start menu).
3. Go to the folder where you put the file, for example:
   
   ```
   cd Desktop
   ```
4. Start the app:
   
   ```
   python johnny_migrator.py
   ```
   
   A window will open.

Alternatively, after the first run from the terminal you can also
double-click `johnny_migrator.py` if Windows has associated the `.py`
extension with Python.

> **NOTE:** Once started and used, the app will create **2 more files**:
> 
> - `migrator_config.json` is a configuration file, created in the same
>   folder as `johnny_migrator.py`. It lets the app remember the paths
>   you entered, your custom search keywords, etc.
> - `migration_log.csv` records every move you make, created inside the
>   root folder, with date/time, original path and destination path —
>   useful as a history log or for later checks.

## How to use it

1. **Index file**: select the text file (Markdown `.md` or `.txt`) that
   describes your list of folders.

2. **Organized root folder**: select the main folder where you've already
   created your Johnny.Decimal tree on disk.

3. **Source folders**: add one or more folders full of files to sort
   (e.g. Desktop, Downloads, an old "To sort" folder).

4. Choose whether to also search inside the source folders' subfolders,
   and whether the date prefix should use the file's **creation** or
   **last modified** date.
   
   There's also a "Show subfolders as whole blocks too" checkbox: when
   enabled (recommended), when the scan finds a subfolder (e.g. `nice documents/` containing doc1, doc2, doc3) the app proposes it **first** as a single block, with the same actions as individual files:
   
   - **Move ✔** moves and renames the entire folder all together
     (e.g. `2026.08.27_Nice_Documents`), inner files included.
   - **🗑 Send to Recycle Bin** sends the whole folder to the Recycle Bin.
   - **Skip ⏭ / 🚫 Never include** apply to the whole folder.
   
   If you choose **Skip** (or **Never include**) on that folder,
   the app switches from treating it as a block to going through its
   individual files one by one, exactly as if you had "entered" it.
   
   To see what's inside a folder **before** deciding, you don't need to
   open File Explorer: as soon as the folder is proposed, the app shows
   directly in the card a list of its contents (names, sizes, and how
   many items each subfolder has).
   
   Right below that you'll find the **"Also rename the inner files with
   their own date prefix"** checkbox (on by default): if you leave it on
   and then press **Move ✔**, besides moving and renaming the folder
   itself, the app renames *all* the files inside it in bulk (including
   in subfolders), without you having to review them one by one — but
   **each with its own date** of creation/last modification (the same
   setting chosen above), not the folder's date:
   
   ```
   2026.08.30_Nice_Documents/
     2024.03.15_Doc1.txt      (doc1's own date)
     2025.11.02_Doc2.txt      (doc2's own date)
     2026.01.20_Doc3.txt      (doc3's own date)
   ```
   
   Subfolder names are left untouched, only files are renamed. Turn the
   checkbox off if, for that folder, you want to move it without
   touching the inner files' names.
   
   ⚠️ **Note on undo**: if you later use "Undo last action" on a move of
   this kind, the folder goes back to its original location, but the
   files inside it **keep their renamed names** (undo only restores the
   folder's location, not the original names of the individual files
   that were inside).

5. **Folders to exclude from scanning**: if you already know in advance
   that a source folder contains subfolders to skip upfront, add them here before scanning. They won't even be explored: no file inside them will end up in the
   queue.

6. Click "Save and scan".

7. For each item you'll find:
   
   - Name, size, creation/modification date, current folder.
   - Two buttons, **👁 Open file** and **📂 Open folder**, handy if you
     don't remember what something is: the first opens it with the
     Windows default app, the second opens File Explorer in the folder
     containing it, with the item already selected.
   - Up to 3 suggested folders as clickable buttons.
   - A search box to manually find any other folder in the index.
   - A "Clean name" field already pre-filled
     (First_Letter_Capitalized_Per_Word, no spaces) that you can freely
     edit: the preview below shows the final name the file will get,
     including the date prefix.

8. Click **Move ✔** to confirm, or **Skip ⏭ (for now)** to put that item
   off for later (it stays where it is and will show up again on the
   next scan).

9. If instead something shouldn't be part of the new system at all (e.g.
   junk, duplicates, stuff to throw away later), use **🚫 Never
   include**: it stays where it is, untouched and not deleted, but the
   app stops proposing it forever in any future scan. On the initial
   screen you'll find a count of how many exclusions you've built up
   this way, with a button to reset them if you change your mind.

10. If something you really want to throw away, use **🗑 Send to Recycle
    Bin**: it moves it to the Windows Recycle Bin (recoverable from there
    like any normally deleted item, until you empty the Recycle Bin).

11. If you make a mistake, **Undo last action ↩** puts the last moved
    item back exactly where it was, with its original name (this only
    applies to moves, not to items sent to the Recycle Bin or excluded).

## Keyboard shortcuts

In the review screen you can do almost everything without the mouse:

| Keys                 | Action                                    |
| -------------------- | ----------------------------------------- |
| `Enter`              | Move ✔ (confirm with the selected folder) |
| `Ctrl` + `→`         | Skip ⏭ (for now)                          |
| `Ctrl` + `1`/`2`/`3` | Select the 1st/2nd/3rd suggestion         |
| `Ctrl` + `F`         | Jump to the manual search box             |
| `Ctrl` + `I`         | 🚫 Never include                          |
| `Ctrl` + `Del`       | 🗑 Send to Recycle Bin                    |
| `Ctrl` + `Z`         | ↩ Undo last action                        |
| `Ctrl` + `O`         | 👁 Open file                              |
| `Ctrl` + `L`         | 📂 Open folder                            |

## Customizing suggestion keywords

The **🔑 Manage suggestion keywords** button (on the initial screen) opens
a window where, for each folder in the index, you can add extra keywords
on top of the ones already extracted automatically from the title. Useful
for synonyms, proper names, acronyms or terms your files' names use but
that don't appear in the folder's title.

- Search for the folder in the list on the left (folders with custom
  keywords have a 🔑 next to them).
- Select it, type a word in the field below and press Enter or "Add".
- "Remove selected" removes a word from the list.

Changes are saved immediately to the configuration file and remain valid
for future scans.

**Special extension keywords**: if you type a word starting with a dot,
e.g. `.epub` or `.pgn`, the app doesn't search for it in the file name but
compares it directly against the extension — useful for categorizing
certain file types (`.epub` for instance is a common e-book format)
without needing the file name to contain recognizable words.

## ***IMPORTANT***: How the index is read

The index file is a simple text list with indentation (spaces or tabs),
read line by line. Each line is classified based on its content, not its
position: the indentation depth only serves to reconstruct "what's inside
what", not to decide the line's type.

The recognition rules, in order:

1. **Area** — lines starting with two digits, a dash, two digits
   (`10-19 Personal Life`). These are only containers/labels, never a
   destination.
2. **Category** — lines starting with two digits with no dot (`11 Me and
   other living beings`). These are containers too.
3. **Group** ([OPTIONAL](https://johnnydecimal.com/documentation/headers)) — lines in the `XX.YY` format that contain the
   `■` symbol (`11.10 ■ Personal documents`). These are an extra
   organizational level, not a destination: they group the folders under
   them, but files don't go directly inside them.
4. **Leaf folder (actual destination)** — all other lines in the `XX.YY
   Title` format (without `■`), e.g. `11.11 Birth certificates`. These
   are the only ones proposed as a destination for your files.

### In practice:

**the `■` symbol is what distinguishes a container from an actual
destination**, not the indentation depth or the number of digits. This
makes the parser reasonably tolerant: you can have categories with or
without a "group" level in between (the app handles both cases
automatically), and small indentation inconsistencies (mixed tabs and
spaces) cause no problems, because the hierarchy is rebuilt with a stack
that only checks if a line is indented more than the previous one, not
a fixed number of spaces.

For each leaf folder found, the app also builds a "breadcrumb" (the full
path of parent titles, later used to extract automatic keywords.

### ***ADVANCED:*** If your index has a different format

If your file doesn't follow this scheme (e.g. you use a different symbol
than `■` for groups, or codes with a different number of digits), the
parser might not recognize the lines correctly. In that case, the three
regular expressions at the top of the file need to be adjusted:

```python
RE_AREA = re.compile(r"^\d{2}-\d{2}\s")
RE_CATEGORY = re.compile(r"^(\d{2})\s+\S")
RE_LEAF_OR_GROUP = re.compile(r"^(\d{2}\.\d{2})\s+(.*)$")
```

and the `"■" in text` condition in the `classify_line()` function, which
decides whether an `XX.YY` line is a group (container) or a leaf
(destination).

### How leaf folders are matched to the real ones on disk

The index file only describes the structure "on paper". When you need to
move a file, the app looks inside the specified root folder for a real
folder whose name starts with the same code as the chosen leaf (e.g. it
looks for a folder starting with `11.11`, anywhere inside the root, at any
depth). The rest of the real folder's name (e.g. `11.11 Birth
certificates`) doesn't need to match the index title exactly: only the
leading code matters.

If the folder doesn't exist on disk yet, the app tells you and asks for
confirmation before creating it (named `CODE Title`, taken from the
index) — it never creates "made up" folders that aren't already planned
in the index.

## Safety of your files

- The app **moves** items (it doesn't duplicate them), but only after
  your explicit confirmation on each one.
- It never overwrites an existing file or folder: in case of a name clash
  at the destination, it adds a numeric suffix.
- It automatically ignores system files like `desktop.ini`, and temporary
  files (`.tmp`, `.part`, `.crdownload`).
- If a destination folder planned in the index doesn't exist on disk yet,
  it tells you and asks for confirmation before creating it — it never
  creates "made up" ones outside the index (this comes in handy for
  things you forgot to create, **it's not recommended to recreate the
  whole tree with this feature**).

## Bonus for uploading to the Cloud

If, like me, you're interested in uploading your finished folder tree with
all its files in order to the cloud, know that many services don't allow
uploading empty folders.
To work around this, I've included the `Script_file_placeholder.ps1`
file: it's simply a script you run with PowerShell that drops an empty
text file called `placeholder.txt` into every folder it finds empty.

### How to use it

1. Copy the `Script_file_placeholder.ps1` file into the root folder;
2. Right-click it and choose `Run with PowerShell`;
3. If a popup appears, confirm with `Open`;
4. The PowerShell window will open; if it asks you to update permissions
   to run this type of file, type `y` to confirm and press Enter;
5. Check the empty folders — `placeholder.txt` should now be inside them.
   Go ahead and upload the whole folder tree to the cloud!

## License

Distributed under the MIT license — see the `LICENSE` file.
