import sys
import shlex
import subprocess
from pathlib import Path
import os
import webbrowser
import json
from typing import List, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import scrolledtext
import tkinter.font as tkfont

# Optional Markdown/HTML rendering support
try:
    from tkhtmlview import HTMLScrolledText  # type: ignore
    _HAS_HTML = True
except Exception:
    _HAS_HTML = False
try:
    import markdown as _md  # type: ignore
    _HAS_MD = True
except Exception:
    _HAS_MD = False

SCRIPT_NAME = "import_mangadex_bookmarks_to_suwayomi_refactored.py"
PACKAGED_CLI = "import_mangadex_bookmarks_to_suwayomi_refactored.exe"

# App metadata (update as needed for releases)
APP_VERSION = "dev"
REPO_URL = "https://github.com/TaliesinDS/Seiyomi"
APP_AUTHOR = "Arthur Kortekaas (TaliesinDS)"
APP_LICENSE = "MIT"

# --- UI helpers: simple tooltip ---
class _Tooltip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tipwin = None
        widget.bind('<Enter>', self._show)
        widget.bind('<Leave>', self._hide)

    def _show(self, event=None):
        if self.tipwin or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        self.tipwin = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(tw, text=self.text, justify='left', relief='solid', borderwidth=1,
                       background='#ffffe0', foreground='#000000', padx=6, pady=4, font=('Segoe UI', 9))
        lbl.pack()

    def _hide(self, event=None):
        if self.tipwin is not None:
            try:
                self.tipwin.destroy()
            except Exception:
                pass
            self.tipwin = None

def attach_tip(widget, text: str):
    try:
        _Tooltip(widget, text)
    except Exception:
        pass

def find_cli_executable() -> Optional[Path]:
    here = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    exe = here / PACKAGED_CLI
    return exe if exe.exists() else None


def python_executable() -> str:
    return sys.executable or "python"


def _pwsh_binary() -> str:
    for cand in ("pwsh", "powershell"):
        try:
            subprocess.run([cand, "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return cand
        except Exception:
            continue
    return "powershell"


def _quote_pwsh_arg(arg: str) -> str:
    escaped = arg.replace("'", "''")
    return f"'{escaped}'"


def _build_pwsh_command(args: List[str], tee_path: Optional[str] = None) -> str:
    if not args:
        return ""
    quoted_args = [_quote_pwsh_arg(a) for a in args]
    command = f"& {quoted_args[0]}"
    if len(quoted_args) > 1:
        command += " " + " ".join(quoted_args[1:])
    if tee_path:
        command += f" | Tee-Object -FilePath {_quote_pwsh_arg(tee_path)}"
    return command


def build_args(v: dict) -> List[str]:
    # Positional args first
    positional: List[str] = []
    if v.get('input_file') and v['input_file'].get().strip():
        positional.append(v['input_file'].get().strip())

    args: List[str] = []
    base_url = v['base_url'].get().strip()
    if base_url:
        args += ["--base-url", base_url]

    # Suwayomi auth / connection
    if v.get('auth_mode') and v['auth_mode'].get().strip():
        args += ["--auth-mode", v['auth_mode'].get().strip()]
    if v.get('su_user') and v['su_user'].get().strip():
        args += ["--username", v['su_user'].get().strip()]
    if v.get('su_pass') and v['su_pass'].get().strip():
        args += ["--password", v['su_pass'].get().strip()]
    if v.get('su_token') and v['su_token'].get().strip():
        args += ["--token", v['su_token'].get().strip()]
    if v.get('insecure') and v['insecure'].get():
        args += ["--insecure"]
    if v.get('request_timeout') and v['request_timeout'].get().strip():
        args += ["--request-timeout", v['request_timeout'].get().strip()]

    # Execution controls
    if v.get('no_title_fallback') and v['no_title_fallback'].get():
        args += ["--no-title-fallback"]
    if v.get('no_progress') and v['no_progress'].get():
        args += ["--no-progress"]
    if v.get('throttle') and v['throttle'].get().strip() and v['throttle'].get().strip() != '0.0':
        args += ["--throttle", v['throttle'].get().strip()]

    # Utilities
    if v.get('list_categories') and v['list_categories'].get():
        args += ["--list-categories"]

    # MangaDex Import
    if v['md_import_enabled'].get():
        args += ["--from-follows"]
        if v['md_user'].get().strip():
            args += ["--md-username", v['md_user'].get().strip()]
        if v['md_pass'].get().strip():
            args += ["--md-password", v['md_pass'].get().strip()]
        if v['md_client_id'].get().strip():
            args += ["--md-client-id", v['md_client_id'].get().strip()]
        if v['md_client_secret'].get().strip():
            args += ["--md-client-secret", v['md_client_secret'].get().strip()]
        if v['md_2fa'].get().strip():
            args += ["--md-2fa", v['md_2fa'].get().strip()]
        if v['debug_login'].get():
            args += ["--debug-login"]
        if v['debug_follows'].get():
            args += ["--debug-follows"]
        if v['max_follows'].get().strip():
            args += ["--max-follows", v['max_follows'].get().strip()]
        if v['md_import_json'].get().strip():
            args += ["--follows-json", v['md_import_json'].get().strip()]

    # Lists
    if v.get('import_lists') and v['import_lists'].get():
        args += ["--import-lists"]
    if v.get('list_lists') and v['list_lists'].get():
        args += ["--list-lists"]
    if v.get('lists_category_map') and v['lists_category_map'].get().strip():
        args += ["--lists-category-map", v['lists_category_map'].get().strip()]
    if v.get('lists_ignore') and v['lists_ignore'].get().strip():
        args += ["--lists-ignore", v['lists_ignore'].get().strip()]
    if v.get('debug_lists') and v['debug_lists'].get():
        args += ["--debug-lists"]

    # Reading statuses
    if v['import_status'].get():
        args += ["--import-reading-status"]
    if v.get('status_map') and v['status_map'].get().strip():
        args += ["--status-category-map", v['status_map'].get().strip()]
    if v.get('status_default_category') and v['status_default_category'].get().strip():
        args += ["--status-default-category", v['status_default_category'].get().strip()]
    if v.get('include_library_statuses') and v['include_library_statuses'].get():
        args += ["--include-library-statuses"]
    if v.get('library_statuses_only') and v['library_statuses_only'].get():
        args += ["--library-statuses-only"]
    if v.get('assume_missing_status') and v['assume_missing_status'].get().strip():
        args += ["--assume-missing-status", v['assume_missing_status'].get().strip()]
    if v.get('print_status_summary') and v['print_status_summary'].get():
        args += ["--print-status-summary"]
    if v.get('debug_status') and v['debug_status'].get():
        args += ["--debug-status"]
    if v.get('status_endpoint_raw') and v['status_endpoint_raw'].get():
        args += ["--status-endpoint-raw"]
    if v.get('status_fallback_single') and v['status_fallback_single'].get():
        args += ["--status-fallback-single"]
    if v.get('status_fallback_throttle') and v['status_fallback_throttle'].get().strip() and v['status_fallback_throttle'].get().strip() != '0.3':
        args += ["--status-fallback-throttle", v['status_fallback_throttle'].get().strip()]
    if v.get('ignore_statuses') and v['ignore_statuses'].get().strip():
        args += ["--ignore-statuses", v['ignore_statuses'].get().strip()]
    if v.get('status_map_debug') and v['status_map_debug'].get():
        args += ["--status-map-debug"]
    if v.get('verify_ids') and v['verify_ids'].get().strip():
        parts = [p.strip() for p in v['verify_ids'].get().replace(';', ',').split(',') if p.strip()]
        for vid in parts:
            args += ["--verify-id", vid]
    if v.get('export_statuses') and v['export_statuses'].get().strip():
        args += ["--export-statuses", v['export_statuses'].get().strip()]

    # CSV import
    csv_files = [p for p in v.get('_csv_files', []) if isinstance(p, str) and p.strip()]
    csv_apply_progress = bool(v.get('csv_apply_read_progress') and v['csv_apply_read_progress'].get())
    if v.get('csv_enabled') and v['csv_enabled'].get() and csv_files:
        for path in csv_files:
            args += ["--from-csv", path]
        csv_kind = v['csv_kind'].get().strip().lower() if v.get('csv_kind') else ''
        if csv_kind and csv_kind != 'auto':
            args += ["--csv-kind", csv_kind]
        raw_col_map = v['csv_col_map'].get().strip() if v.get('csv_col_map') else ''
        if raw_col_map:
            for entry in [seg.strip() for seg in raw_col_map.replace(';', '\n').splitlines() if seg.strip()]:
                args += ["--csv-col-map", entry]
        raw_status_map = v['csv_status_to_category'].get().strip() if v.get('csv_status_to_category') else ''
        if raw_status_map:
            args += ["--csv-status-to-category", raw_status_map]
        threshold = v['csv_title_threshold'].get().strip() if v.get('csv_title_threshold') else ''
        if threshold and threshold != '0.6':
            args += ["--csv-title-threshold", threshold]
        if v.get('csv_title_strict') and v['csv_title_strict'].get():
            args += ["--csv-title-strict"]
        if v.get('csv_apply_read_progress') and v['csv_apply_read_progress'].get():
            args += ["--csv-apply-read-progress"]
        if v.get('csv_prefer_existing') and v['csv_prefer_existing'].get():
            args += ["--csv-prefer-existing"]
        args += ["--csv-no-mangadex"]

    # Read chapters (MangaDex session-dependent)
    import_read_enabled = bool(v.get('import_read') and v['import_read'].get())
    if import_read_enabled:
        args += ["--import-read-chapters"]
        if v.get('read_chapters_dry_run') and v['read_chapters_dry_run'].get():
            args += ["--read-chapters-dry-run"]
        if v.get('read_delay') and v['read_delay'].get().strip() and v['read_delay'].get().strip() != '0.0':
            args += ["--read-sync-delay", v['read_delay'].get().strip()]
        if v.get('max_read_requests_per_minute') and v['max_read_requests_per_minute'].get().strip() and v['max_read_requests_per_minute'].get().strip() != '300':
            args += ["--max-read-requests-per-minute", v['max_read_requests_per_minute'].get().strip()]
        if v.get('read_sync_number_fallback') and v['read_sync_number_fallback'].get():
            args += ["--read-sync-number-fallback"]
        if v.get('missing_report') and v['missing_report'].get().strip():
            args += ["--missing-report", v['missing_report'].get().strip()]

    # Shared read-sync modifiers (MangaDex or CSV apply-progress)
    if import_read_enabled or csv_apply_progress:
        if v.get('read_sync_across_sources') and v['read_sync_across_sources'].get():
            args += ["--read-sync-across-sources"]
        if v.get('read_sync_only_if_ahead') and v['read_sync_only_if_ahead'].get():
            args += ["--read-sync-only-if-ahead"]

    filter_title_arg = v['filter_title'].get().strip() if v.get('filter_title') else ''

    # Category
    if v['category_id'].get().strip():
        args += ["--category-id", v['category_id'].get().strip()]

    # Rehoming
    if v.get('rehoming_enabled') and v['rehoming_enabled'].get():
        args += ["--rehoming-enabled"]
        if v.get('rehoming_sources') and v['rehoming_sources'].get().strip():
            args += ["--rehoming-sources", v['rehoming_sources'].get().strip()]
        if v.get('rehoming_skip_ge') and v['rehoming_skip_ge'].get().strip() and v['rehoming_skip_ge'].get().strip() != '1':
            args += ["--rehoming-skip-if-chapters-ge", v['rehoming_skip_ge'].get().strip()]
        if v.get('rehoming_remove_mangadex') and v['rehoming_remove_mangadex'].get():
            args += ["--rehoming-remove-source"]
        # Reuse title-matching options when rehoming is enabled
        if v.get('migrate_title_threshold') and v['migrate_title_threshold'].get().strip() and v['migrate_title_threshold'].get().strip() != '0.6':
            args += ["--migrate-title-threshold", v['migrate_title_threshold'].get().strip()]
        if v.get('migrate_title_strict') and v['migrate_title_strict'].get():
            args += ["--migrate-title-strict"]

    # Migration
    if v['migrate_lib'].get():
        args += ["--migrate-library"]
        if v.get('migrate_threshold') and v['migrate_threshold'].get().strip() and v['migrate_threshold'].get().strip() != '1':
            args += ["--migrate-threshold-chapters", v['migrate_threshold'].get().strip()]
        if v.get('migrate_include_categories') and v['migrate_include_categories'].get().strip():
            args += ["--migrate-include-categories", v['migrate_include_categories'].get().strip()]
        if v.get('migrate_exclude_categories') and v['migrate_exclude_categories'].get().strip():
            args += ["--migrate-exclude-categories", v['migrate_exclude_categories'].get().strip()]
        if v['migrate_sources'].get().strip():
            args += ["--migrate-sources", v['migrate_sources'].get().strip()]
        if v['exclude_sources'].get().strip():
            args += ["--exclude-sources", v['exclude_sources'].get().strip()]
        if v['migrate_pref_only'].get():
            args += ["--migrate-preferred-only"]
        if v['best_source'].get():
            args += ["--best-source"]
        if v.get('best_source_candidates') and v['best_source_candidates'].get().strip() and v['best_source_candidates'].get().strip() != '5':
            args += ["--best-source-candidates", v['best_source_candidates'].get().strip()]
        if v.get('min_chapters_per_alt') and v['min_chapters_per_alt'].get().strip() and v['min_chapters_per_alt'].get().strip() != '0':
            args += ["--min-chapters-per-alt", v['min_chapters_per_alt'].get().strip()]
        if v['best_global'].get():
            args += ["--best-source-global"]
        if v['best_canon'].get():
            args += ["--best-source-canonical"]
        if v['pref_langs'].get().strip():
            args += ["--preferred-langs", v['pref_langs'].get().strip()]
        if v['lang_fallback'].get():
            args += ["--lang-fallback"]
        if v['prefer_sources'].get().strip():
            args += ["--prefer-sources", v['prefer_sources'].get().strip()]
        if v['prefer_boost'].get().strip() and v['prefer_boost'].get().strip() != '3':
            args += ["--prefer-boost", v['prefer_boost'].get().strip()]
        if v['keep_both'].get():
            args += ["--migrate-keep-both"]
            if v['keep_both_min'].get().strip() and v['keep_both_min'].get().strip() != '1':
                args += ["--keep-both-min-preferred", v['keep_both_min'].get().strip()]
        # Default is non-destructive; only add removal flag when explicitly enabled
        if v['remove_original'].get():
            args += ["--migrate-remove"]
        if v.get('migrate_remove_if_duplicate') and v['migrate_remove_if_duplicate'].get():
            args += ["--migrate-remove-if-duplicate"]
        if v.get('migrate_timeout') and v['migrate_timeout'].get().strip() and v['migrate_timeout'].get().strip() != '20.0':
            args += ["--migrate-timeout", v['migrate_timeout'].get().strip()]
        if v.get('migrate_max_sources_per_site') and v['migrate_max_sources_per_site'].get().strip() and v['migrate_max_sources_per_site'].get().strip() != '3':
            args += ["--migrate-max-sources-per-site", v['migrate_max_sources_per_site'].get().strip()]
        if v.get('migrate_try_second_page') and v['migrate_try_second_page'].get():
            args += ["--migrate-try-second-page"]
        if filter_title_arg:
            args += ["--migrate-filter-title", filter_title_arg]
            filter_title_arg = ''
        # Title matching options
        if v.get('migrate_title_threshold') and v['migrate_title_threshold'].get().strip() and v['migrate_title_threshold'].get().strip() != '0.6':
            args += ["--migrate-title-threshold", v['migrate_title_threshold'].get().strip()]
        if v.get('migrate_title_strict') and v['migrate_title_strict'].get():
            args += ["--migrate-title-strict"]

    # Prune
    if v['prune_zero'].get():
        args += ["--prune-zero-duplicates"]
        if v['prune_thresh'].get().strip() and v['prune_thresh'].get().strip() != '1':
            args += ["--prune-threshold-chapters", v['prune_thresh'].get().strip()]
    if v['prune_nonpref'].get():
        args += ["--prune-nonpreferred-langs"]
        if v['pref_langs'].get().strip():
            args += ["--preferred-langs", v['pref_langs'].get().strip()]
        if v['prune_lang_thresh'].get().strip() and v['prune_lang_thresh'].get().strip() != '1':
            args += ["--prune-lang-threshold", v['prune_lang_thresh'].get().strip()]
        if v['prune_keep_most'].get():
            args += ["--prune-lang-fallback-keep-most"]
    if v['prune_filter_title'].get().strip():
        args += ["--prune-filter-title", v['prune_filter_title'].get().strip()]

    # Misc
    if filter_title_arg:
        args += ["--migrate-filter-title", filter_title_arg]
    if v['dry_run'].get():
        args += ["--dry-run"]
    if v['debug'].get():
        args += ["--debug-library"]

    # Ensure positional input_file is first
    return positional + args


def launch_command(cmd_list: List[str], save_log: bool, log_path: Optional[str], external_terminal: bool):
    pwsh = _pwsh_binary()
    cli_exe = find_cli_executable()
    CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
    CREATE_NEW_CONSOLE = 0x00000010 if os.name == 'nt' else 0

    if external_terminal:
        # Visible terminal with live output
        creation_flag = CREATE_NEW_CONSOLE
        if cli_exe is not None:
            full_cmd = [str(cli_exe), *cmd_list]
            ps_cmd = _build_pwsh_command(full_cmd, log_path if (save_log and log_path) else None)
            subprocess.Popen([pwsh, "-NoExit", "-Command", ps_cmd], creationflags=creation_flag)
            return
        py = python_executable()
        script = str(Path(__file__).parent / SCRIPT_NAME)
        full_cmd = [py, script, *cmd_list]
        ps_cmd = _build_pwsh_command(full_cmd, log_path if (save_log and log_path) else None)
        subprocess.Popen([pwsh, "-NoExit", "-Command", ps_cmd], creationflags=creation_flag)
        return

    # Quiet mode: no external terminal; support logging via hidden pipeline
    if cli_exe is not None:
        full_cmd = [str(cli_exe), *cmd_list]
        if save_log and log_path:
            ps_cmd = _build_pwsh_command(full_cmd, log_path)
            subprocess.Popen([pwsh, "-Command", ps_cmd], creationflags=CREATE_NO_WINDOW)
        else:
            subprocess.Popen(full_cmd, creationflags=CREATE_NO_WINDOW)
        return
    py = python_executable()
    script = str(Path(__file__).parent / SCRIPT_NAME)
    full_cmd = [py, script, *cmd_list]
    if save_log and log_path:
        ps_cmd = _build_pwsh_command(full_cmd, log_path)
        subprocess.Popen([pwsh, "-Command", ps_cmd], creationflags=CREATE_NO_WINDOW)
    else:
        subprocess.Popen(full_cmd, creationflags=CREATE_NO_WINDOW)


def apply_preset(v: dict, name: str):
    if name == 'Prefer English Migration':
        v['migrate_lib'].set(True)
        v['migrate_pref_only'].set(True)
        v['best_source'].set(True)
        v['best_global'].set(False)
        v['best_canon'].set(True)
        v['pref_langs'].set('en,en-us')
        v['lang_fallback'].set(True)
        v['remove_original'].set(True)
        v['dry_run'].set(True)
    elif name == 'Cleanup Non-English':
        v['prune_nonpref'].set(True)
        v['pref_langs'].set('en,en-us')
        v['dry_run'].set(True)
    elif name == 'Keep Both (Quality+Coverage)':
        v['migrate_lib'].set(True)
        v['migrate_pref_only'].set(True)
        v['best_source'].set(True)
        v['best_global'].set(True)
        v['best_canon'].set(True)
        v['pref_langs'].set('en,en-us')
        v['lang_fallback'].set(True)
        v['prefer_sources'].set('asura,flame,genz,utoons')
        v['prefer_boost'].set('3')
        v['keep_both'].set(True)
        v['keep_both_min'].set('1')
        v['remove_original'].set(True)
        v['dry_run'].set(True)
    elif name == 'Read Sync Across Sources':
        # Enable MangaDex import with read sync across sources by chapter number
        v['md_import_enabled'].set(True)
        v['import_read'].set(True)
        v['read_chapters_dry_run'].set(False)
        v['read_delay'].set('2')
        v['max_read_requests_per_minute'].set('240')
        v['read_sync_number_fallback'].set(True)
        v['read_sync_across_sources'].set(True)
        v['read_sync_only_if_ahead'].set(True)
        # Pre-fill a default missing-report path if blank
        if not v['missing_report'].get().strip():
            v['missing_report'].set(str(Path.cwd() / 'reports' / 'md_missing_reads.csv'))


# ---- Config helpers ----

def _config_dir() -> Path:
    base = Path(os.getenv('APPDATA') or Path.home())
    new_dir = base / 'Seiyomi'
    old_dir = base / 'MangaDex_Suwayomi'
    if not new_dir.exists() and old_dir.exists():
        import shutil
        try:
            shutil.copytree(str(old_dir), str(new_dir))
        except Exception:
            pass  # migration best-effort
    return new_dir


def _load_config() -> dict:
    try:
        p = _config_dir() / 'config.json'
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return {}


def _save_config(cfg: dict) -> None:
    try:
        d = _config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / 'config.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    except Exception:
        pass


def main():
    root = tk.Tk()
    root.title('Seiyomi — Suwayomi Database Tool')
    # Early stub to avoid reference-before-definition during initialization
    def _render_preview():
        pass
    # Styles
    try:
        _style = ttk.Style(root)
        _style.configure('Danger.TCheckbutton', foreground='#b00020')
    except Exception:
        pass
    # Optional window icon (PNG). Place a high-res PNG at assets/icon_256.png
    try:
        _icon_path = Path(__file__).parent / 'assets' / 'icon_256.png'
        if _icon_path.exists():
            root._icon_img = tk.PhotoImage(file=str(_icon_path))  # keep ref to avoid GC
            root.iconphoto(True, root._icon_img)
    except Exception:
        pass

    def open_manual():
        manual = Path(__file__).parent / 'USER_MANUAL.md'
        if manual.exists():
            try:
                if os.name == 'nt' and hasattr(os, 'startfile'):
                    os.startfile(str(manual))  # type: ignore[attr-defined]
                    return
            except Exception:
                pass
            try:
                webbrowser.open(manual.as_uri())
                return
            except Exception:
                pass
        messagebox.showinfo('Manual not found', 'USER_MANUAL.md could not be opened. Please open it from the repository root.')

    # Shared Markdown popup viewer (used for manual and README)
    def show_markdown_popup(title: str, file_path: Path, open_external_cb=None):
        if not file_path.exists():
            messagebox.showinfo(f'{title} not found', f'{file_path.name} could not be found in the repository root.')
            return
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to read {file_path.name}: {e}')
            return

        top = tk.Toplevel(root)
        top.title(title)
        top.geometry('900x700')
        try:
            _geo_cfg = _load_config()
            if isinstance(_geo_cfg.get('manual_geometry'), str):
                top.geometry(_geo_cfg['manual_geometry'])
        except Exception:
            pass

        bar = ttk.Frame(top)
        bar.pack(fill='x')

        cfg = _load_config()
        default_sz = str(cfg.get('manual_font_size', 13))
        # Default to rendered markdown when libs are available
        default_render = True if (_HAS_HTML and _HAS_MD) else False
        default_dark = bool(cfg.get('manual_dark_mode', False))

        render_md = tk.BooleanVar(top, value=default_render)
        size_var = tk.StringVar(top, value=default_sz)
        dark_var = tk.BooleanVar(top, value=default_dark)
        find_var = tk.StringVar(top, value=str(cfg.get('manual_find_text', '')))
        case_var = tk.BooleanVar(top, value=bool(cfg.get('manual_find_case', False)))

        ttk.Label(bar, text='Font size').pack(side='left', padx=(6, 2))
        size_spin = ttk.Spinbox(bar, from_=8, to=24, width=4, textvariable=size_var)
        size_spin.pack(side='left', padx=(0, 6), pady=4)
        ttk.Button(bar, text='Apply', command=lambda: _apply_size()).pack(side='left', padx=(0, 6), pady=4)
        ttk.Checkbutton(bar, text='Rendered Markdown', variable=render_md, command=lambda: _switch_mode()).pack(side='left', padx=(6, 6))
        ttk.Checkbutton(bar, text='Dark', variable=dark_var, command=lambda: _switch_mode()).pack(side='left', padx=(0, 6))

        ttk.Label(bar, text='Find').pack(side='left')
        find_entry = ttk.Entry(bar, textvariable=find_var, width=28)
        find_entry.pack(side='left', padx=(4, 2))
        ttk.Checkbutton(bar, text='Aa', variable=case_var, command=lambda: (_rebuild_find())).pack(side='left', padx=(2, 6))
        ttk.Button(bar, text='Prev', command=lambda: _find_prev()).pack(side='left', padx=(0, 2))
        ttk.Button(bar, text='Next', command=lambda: _find_next()).pack(side='left', padx=(0, 6))

        if open_external_cb is not None:
            ttk.Button(bar, text='Open Externally', command=open_external_cb).pack(side='right', padx=4, pady=4)
        ttk.Button(bar, text='Close', command=top.destroy).pack(side='right', padx=4, pady=4)

        content_frame = ttk.Frame(top)
        content_frame.pack(fill='both', expand=True)

        state = {'mode': 'text', 'widget': None, 'tw': None}
        text_font = tkfont.Font(family='Segoe UI', size=int(size_var.get()))

        def _apply_plain_theme(tw: tk.Text):
            try:
                if dark_var.get():
                    tw.configure(bg='#0f1115', fg='#e6edf3', insertbackground='#e6edf3',
                                 selectbackground='#264f78', selectforeground='#ffffff')
                else:
                    tw.configure(bg='#ffffff', fg='#000000', insertbackground='#000000',
                                 selectbackground='#bcdfff', selectforeground='#000000')
            except Exception:
                pass

        def _render_html():
            html_body = _md.markdown(content, extensions=['extra', 'fenced_code', 'sane_lists', 'tables', 'toc'])
            try:
                sz = max(8, min(36, int(size_var.get())))
            except Exception:
                sz = 13
            if dark_var.get():
                html = (
                    f"<div style=\"font-family:Segoe UI, Arial, sans-serif; font-size:{sz}px; line-height:1.6; padding:10px; color:#e6edf3; background-color:#0f1115;\">{html_body}</div>"
                )
            else:
                html = f"<div style=\"font-family:Segoe UI, Arial, sans-serif; font-size:{sz}px; line-height:1.5; padding:10px;\">{html_body}</div>"
            viewer = HTMLScrolledText(content_frame, html=html)

            def _find_text_widget(w: tk.Widget):
                if isinstance(w, tk.Text):
                    return w
                for ch in w.winfo_children():
                    twx = _find_text_widget(ch)
                    if twx is not None:
                        return twx
                return None

            tw = _find_text_widget(viewer)
            if tw is not None:
                try:
                    tw.configure(state='normal', exportselection=False,
                                 selectbackground='#bcdfff', selectforeground='#000000',
                                 inactiveselectbackground='#dceeff', cursor='xterm', wrap='word')
                    tw.tag_configure('SEL_CUSTOM', background='#bcdfff', foreground='#000000')
                    tw.tag_raise('SEL_CUSTOM')
                    _apply_plain_theme(tw)

                    def _update_sel(event=None):
                        try:
                            start = tw.index('sel.first')
                            end = tw.index('sel.last')
                        except tk.TclError:
                            tw.tag_remove('SEL_CUSTOM', '1.0', 'end')
                            return
                        tw.tag_remove('SEL_CUSTOM', '1.0', 'end')
                        tw.tag_add('SEL_CUSTOM', start, end)

                    for seq in ('<<Selection>>', '<ButtonRelease-1>', '<B1-Motion>', '<KeyRelease>'):
                        tw.bind(seq, _update_sel, add='+')
                    tw.focus_set()
                except Exception:
                    pass
            viewer.pack(fill='both', expand=True)
            state['mode'] = 'html'
            state['widget'] = viewer
            state['tw'] = tw

        def _render_text():
            txt = scrolledtext.ScrolledText(content_frame, wrap='word')
            txt.pack(fill='both', expand=True)
            txt.insert('1.0', content)
            txt.configure(state='disabled', font=text_font)
            _apply_plain_theme(txt)
            state['mode'] = 'text'
            state['widget'] = txt
            state['tw'] = txt

        def _clear_content():
            for child in content_frame.winfo_children():
                child.destroy()

        def _persist():
            try:
                cur_sz = int(size_var.get())
            except Exception:
                cur_sz = 13
            cfg.update({
                'manual_font_size': cur_sz,
                'manual_render_md': bool(render_md.get()),
                'manual_dark_mode': bool(dark_var.get()),
                'manual_find_text': find_var.get(),
                'manual_find_case': bool(case_var.get()),
                'manual_geometry': top.winfo_geometry(),
            })
            _save_config(cfg)

        def _apply_size():
            try:
                new_size = int(size_var.get())
            except Exception:
                new_size = 13
            if state['mode'] == 'text':
                text_font.configure(size=new_size)
            elif state['mode'] == 'html':
                _clear_content()
                _render_html()
            _persist()
            _rebuild_find()

        def _switch_mode():
            _clear_content()
            if render_md.get() and _HAS_HTML and _HAS_MD:
                try:
                    _render_html()
                except Exception:
                    _render_text()
            else:
                _render_text()
            _persist()
            _rebuild_find()

        def _on_close():
            _persist()
            top.destroy()
        top.protocol('WM_DELETE_WINDOW', _on_close)

        if render_md.get():
            try:
                _render_html()
            except Exception:
                _render_text()
        else:
            _render_text()

        def _clear_find_tags():
            tw = state.get('tw')
            if not isinstance(tw, tk.Text):
                return
            try:
                tw.tag_remove('FIND_HL', '1.0', 'end')
                tw.tag_remove('FIND_CUR', '1.0', 'end')
            except Exception:
                pass

        def _rebuild_find():
            tw = state.get('tw')
            if not isinstance(tw, tk.Text):
                return
            _clear_find_tags()
            pattern = find_var.get()
            if not pattern:
                return
            try:
                tw.tag_configure('FIND_HL', background='#fff3b0')
                tw.tag_configure('FIND_CUR', background='#ffd54f')
                start = '1.0'
                while True:
                    idx = tw.search(pattern, start, 'end', nocase=(not case_var.get()))
                    if not idx:
                        break
                    end = f"{idx}+{len(pattern)}c"
                    tw.tag_add('FIND_HL', idx, end)
                    start = end
            except Exception:
                pass

        def _goto_match(next_dir: int):
            tw = state.get('tw')
            if not isinstance(tw, tk.Text):
                return
            pattern = find_var.get()
            if not pattern:
                return
            try:
                cur = tw.index('insert')
            except Exception:
                cur = '1.0'
            found_idx = None
            if next_dir >= 0:
                idx = tw.search(pattern, cur, 'end', nocase=(not case_var.get()))
                if not idx:
                    idx = tw.search(pattern, '1.0', 'end', nocase=(not case_var.get()))
                found_idx = idx
            else:
                last_idx = None
                start = '1.0'
                while True:
                    idx = tw.search(pattern, start, 'end', nocase=(not case_var.get()))
                    if not idx or tw.compare(idx, '>=', cur):
                        break
                    last_idx = idx
                    start = f"{idx}+1c"
                found_idx = last_idx
            if found_idx:
                end = f"{found_idx}+{len(pattern)}c"
                try:
                    tw.tag_remove('FIND_CUR', '1.0', 'end')
                    tw.tag_add('FIND_CUR', found_idx, end)
                    tw.mark_set('insert', end)
                    tw.see(found_idx)
                    tw.focus_set()
                except Exception:
                    pass

        def _find_next():
            if not find_var.get():
                return
            _goto_match(1)

        def _find_prev():
            if not find_var.get():
                return
            _goto_match(-1)

        try:
            find_entry.bind('<Return>', lambda e: (_rebuild_find(), _find_next()))
        except Exception:
            pass
        _rebuild_find()

    def show_manual_popup():
        show_markdown_popup('User Manual', Path(__file__).parent / 'USER_MANUAL.md', open_external_cb=open_manual)

    def show_readme_popup():
        show_markdown_popup('README', Path(__file__).parent / 'README.md', open_external_cb=lambda: (os.startfile(str(Path(__file__).parent / 'README.md')) if os.name == 'nt' else webbrowser.open((Path(__file__).parent / 'README.md').as_uri())))

    # GUI values
    vals = {
        # Misc
        'base_url': tk.StringVar(value='http://127.0.0.1:4567'),
        'dry_run': tk.BooleanVar(value=True),
        'debug': tk.BooleanVar(value=False),
        'save_log': tk.BooleanVar(value=False),
        'external_terminal': tk.BooleanVar(value=False),
        'log_path': tk.StringVar(value=''),
        'preset': tk.StringVar(value=''),
        # Input file (optional)
        'input_file': tk.StringVar(value=''),
        # Suwayomi auth/connection
        'auth_mode': tk.StringVar(value='auto'),
        'su_user': tk.StringVar(value=''),
        'su_pass': tk.StringVar(value=''),
        'su_token': tk.StringVar(value=''),
        'insecure': tk.BooleanVar(value=False),
        'request_timeout': tk.StringVar(value='12.0'),
        'no_title_fallback': tk.BooleanVar(value=False),
        'no_progress': tk.BooleanVar(value=False),
        'throttle': tk.StringVar(value='0.0'),
        'list_categories': tk.BooleanVar(value=False),
        # MangaDex Import
        'md_import_enabled': tk.BooleanVar(value=False),
        'md_user': tk.StringVar(value=''),
        'md_pass': tk.StringVar(value=''),
        'md_client_id': tk.StringVar(value=''),
        'md_client_secret': tk.StringVar(value=''),
        'md_2fa': tk.StringVar(value=''),
        'debug_login': tk.BooleanVar(value=False),
        'debug_follows': tk.BooleanVar(value=False),
        'max_follows': tk.StringVar(value=''),
        'md_import_json': tk.StringVar(value=''),
        'import_lists': tk.BooleanVar(value=False),
        'list_lists': tk.BooleanVar(value=False),
        'lists_category_map': tk.StringVar(value=''),
        'lists_ignore': tk.StringVar(value=''),
        'debug_lists': tk.BooleanVar(value=False),
        'import_status': tk.BooleanVar(value=False),
        'status_map': tk.StringVar(value=''),
        'status_default_category': tk.StringVar(value=''),
        'include_library_statuses': tk.BooleanVar(value=False),
        'library_statuses_only': tk.BooleanVar(value=False),
        'assume_missing_status': tk.StringVar(value=''),
        'print_status_summary': tk.BooleanVar(value=False),
        'debug_status': tk.BooleanVar(value=False),
        'status_endpoint_raw': tk.BooleanVar(value=False),
        'status_fallback_single': tk.BooleanVar(value=False),
        'status_fallback_throttle': tk.StringVar(value='0.3'),
        'ignore_statuses': tk.StringVar(value=''),
        'status_map_debug': tk.BooleanVar(value=False),
        'verify_ids': tk.StringVar(value=''),
        'export_statuses': tk.StringVar(value=''),
        'import_read': tk.BooleanVar(value=False),
        'read_chapters_dry_run': tk.BooleanVar(value=False),
        'read_delay': tk.StringVar(value='1'),
        'max_read_requests_per_minute': tk.StringVar(value='300'),
    'read_sync_number_fallback': tk.BooleanVar(value=False),
    'read_sync_across_sources': tk.BooleanVar(value=False),
    'read_sync_only_if_ahead': tk.BooleanVar(value=True),
    'missing_report': tk.StringVar(value=str(Path.cwd() / 'reports' / 'md_missing_reads.csv')),
        'category_id': tk.StringVar(value=''),
        # CSV Import
        'csv_enabled': tk.BooleanVar(value=False),
        'csv_kind': tk.StringVar(value='auto'),
        'csv_col_map': tk.StringVar(value=''),
        'csv_status_to_category': tk.StringVar(value=''),
        'csv_title_threshold': tk.StringVar(value='0.6'),
        'csv_title_strict': tk.BooleanVar(value=False),
        'csv_apply_read_progress': tk.BooleanVar(value=False),
        'csv_prefer_existing': tk.BooleanVar(value=False),
        # Migrate
        'migrate_lib': tk.BooleanVar(value=False),
        'migrate_threshold': tk.StringVar(value='1'),
        'migrate_include_categories': tk.StringVar(value=''),
        'migrate_exclude_categories': tk.StringVar(value=''),
        'migrate_sources': tk.StringVar(value=''),
        'exclude_sources': tk.StringVar(value='comick,hitomi'),
        'migrate_pref_only': tk.BooleanVar(value=False),
        'best_source': tk.BooleanVar(value=False),
        'best_source_candidates': tk.StringVar(value='5'),
        'min_chapters_per_alt': tk.StringVar(value='0'),
        'best_global': tk.BooleanVar(value=False),
        'best_canon': tk.BooleanVar(value=False),
        'pref_langs': tk.StringVar(value='en,en-us'),
        'lang_fallback': tk.BooleanVar(value=False),
        'prefer_sources': tk.StringVar(value='asura,flame,genz,utoons'),
        'prefer_boost': tk.StringVar(value='3'),
        'migrate_title_threshold': tk.StringVar(value='0.6'),
        'migrate_title_strict': tk.BooleanVar(value=False),
        'keep_both': tk.BooleanVar(value=False),
        'keep_both_min': tk.StringVar(value='1'),
        # Default to non-destructive removal
        'remove_original': tk.BooleanVar(value=False),
        'migrate_remove_if_duplicate': tk.BooleanVar(value=False),
        'migrate_timeout': tk.StringVar(value='20.0'),
        'migrate_max_sources_per_site': tk.StringVar(value='3'),
        'migrate_try_second_page': tk.BooleanVar(value=False),
        'filter_title': tk.StringVar(value=''),
        # Rehoming
        'rehoming_enabled': tk.BooleanVar(value=False),
        'rehoming_sources': tk.StringVar(value=''),
        'rehoming_skip_ge': tk.StringVar(value='1'),
        'rehoming_remove_mangadex': tk.BooleanVar(value=False),
        # Prune
        'prune_zero': tk.BooleanVar(value=False),
        'prune_thresh': tk.StringVar(value='1'),
        'prune_nonpref': tk.BooleanVar(value=False),
        'prune_lang_thresh': tk.StringVar(value='1'),
        'prune_keep_most': tk.BooleanVar(value=False),
        'prune_filter_title': tk.StringVar(value=''),
    }

    # Top bar (spacing only)
    topbar = ttk.Frame(root)
    topbar.pack(fill='x', padx=8, pady=(6, 0))

    nb = ttk.Notebook(root)

    # MangaDex Import tab
    fw = ttk.Frame(nb)
    nb.add(fw, text='MangaDex Import')
    r = 0
    # Tab description + help
    desc_fw = ttk.Frame(fw); desc_fw.grid(row=r, column=0, columnspan=4, sticky='we', pady=(4, 6))
    ttk.Label(desc_fw, text='Import followed manga, reading statuses, custom lists, and read chapters from MangaDex into Suwayomi.', foreground='#444').pack(side='left')
    ttk.Button(desc_fw, text='Help', width=5, command=lambda: (_save_config({**_load_config(), 'manual_find_text': 'MangaDex Import'}), show_manual_popup())).pack(side='right')
    r += 1
    cb_md_enable = ttk.Checkbutton(fw, text='Enable MangaDex Import', variable=vals['md_import_enabled'])
    cb_md_enable.grid(row=r, column=0, sticky='w'); r+=1
    attach_tip(cb_md_enable, 'When enabled, includes your MangaDex follows in the processing set. See manual: MangaDex Import')
 
    # Login / follows
    lf = ttk.LabelFrame(fw, text='MangaDex Login & Follows')
    lf.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(4,6))
    rr = 0
    ttk.Label(lf, text='MD Username').grid(row=rr, column=0, sticky='w'); en_md_user = ttk.Entry(lf, textvariable=vals['md_user'], width=25); en_md_user.grid(row=rr, column=1, sticky='w')
    attach_tip(en_md_user, 'Your MangaDex account username. Used to authenticate for follows/status import.')
    ttk.Label(lf, text='MD Password').grid(row=rr, column=2, sticky='e'); en_md_pass = ttk.Entry(lf, textvariable=vals['md_pass'], show='*', width=25); en_md_pass.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_md_pass, 'Your MangaDex password. Used to obtain an access token. Not stored.')
    ttk.Label(lf, text='Client ID').grid(row=rr, column=0, sticky='w'); en_md_cid = ttk.Entry(lf, textvariable=vals['md_client_id'], width=25); en_md_cid.grid(row=rr, column=1, sticky='w')
    attach_tip(en_md_cid, 'Optional MangaDex OAuth client id. Usually leave blank for default OAuth.')
    ttk.Label(lf, text='Client Secret').grid(row=rr, column=2, sticky='e'); en_md_csec = ttk.Entry(lf, textvariable=vals['md_client_secret'], show='*', width=25); en_md_csec.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_md_csec, 'Optional MangaDex OAuth client secret. Leave blank unless you know you need it.')
    ttk.Label(lf, text='2FA / OTP').grid(row=rr, column=0, sticky='w'); en_md_otp = ttk.Entry(lf, textvariable=vals['md_2fa'], width=25); en_md_otp.grid(row=rr, column=1, sticky='w')
    attach_tip(en_md_otp, 'If your MangaDex account uses 2FA, enter the current one-time code here.')
    cb_dbg_login = ttk.Checkbutton(lf, text='Debug login', variable=vals['debug_login']); cb_dbg_login.grid(row=rr, column=2, sticky='w')
    attach_tip(cb_dbg_login, 'Print diagnostic info on login failures (password is redacted).')
    cb_dbg_fol = ttk.Checkbutton(lf, text='Debug follows', variable=vals['debug_follows']); cb_dbg_fol.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(cb_dbg_fol, 'Verbose pagination logs when fetching follows.')
    ttk.Label(lf, text='Max follows').grid(row=rr, column=0, sticky='w'); en_max_f = ttk.Entry(lf, textvariable=vals['max_follows'], width=10); en_max_f.grid(row=rr, column=1, sticky='w')
    attach_tip(en_max_f, 'Optional limit used for testing (leave blank for all).')
    ttk.Label(lf, text='Save import JSON').grid(row=rr, column=2, sticky='e'); en_md_json = ttk.Entry(lf, textvariable=vals['md_import_json'], width=30); en_md_json.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_md_json, 'If set, writes fetched follows (id + title) to this file.')
    bt_json = ttk.Button(lf, text='Browse...', command=lambda: vals['md_import_json'].set(filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON','*.json')])))
    bt_json.grid(row=rr, column=3, sticky='e'); rr+=1
    attach_tip(bt_json, 'Choose where to save the exported follows JSON.')

    r += 1

    # Lists
    ll = ttk.LabelFrame(fw, text='Custom Lists')
    ll.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(0,6))
    rr = 0
    cb_imp_lists = ttk.Checkbutton(ll, text='Import lists', variable=vals['import_lists']); cb_imp_lists.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_imp_lists, 'Fetch MangaDex custom lists and map list names to categories.')
    cb_list_lists = ttk.Checkbutton(ll, text='List lists (and exit)', variable=vals['list_lists']); cb_list_lists.grid(row=rr, column=1, sticky='w'); rr+=1
    attach_tip(cb_list_lists, 'Print your MangaDex custom lists (id + name) and exit.')
    ttk.Label(ll, text='Lists->Category map').grid(row=rr, column=0, sticky='w'); en_lists_map = ttk.Entry(ll, textvariable=vals['lists_category_map'], width=50); en_lists_map.grid(row=rr, column=1, columnspan=3, sticky='we'); rr+=1
    attach_tip(en_lists_map, 'Map list names to Suwayomi category IDs. Example: Reading=4,Completed=9')
    ttk.Label(ll, text='Ignore lists').grid(row=rr, column=0, sticky='w'); en_lists_ignore = ttk.Entry(ll, textvariable=vals['lists_ignore'], width=50); en_lists_ignore.grid(row=rr, column=1, columnspan=3, sticky='we'); rr+=1
    attach_tip(en_lists_ignore, 'Comma-separated list names to ignore (e.g. Reading)')
    cb_lists_dbg = ttk.Checkbutton(ll, text='Debug lists', variable=vals['debug_lists']); cb_lists_dbg.grid(row=rr, column=0, sticky='w'); rr+=1
    attach_tip(cb_lists_dbg, 'Verbose logs for lists fetching and mapping decisions.')
    r += 1

    # Statuses & Reading
    sf = ttk.LabelFrame(fw, text='Statuses & Reading')
    sf.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(0,6))
    rr = 0
    cb_import_status = ttk.Checkbutton(sf, text='Import reading statuses', variable=vals['import_status'])
    cb_import_status.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_import_status, 'Fetch MangaDex reading statuses and map them to Suwayomi categories.')
    ttk.Label(sf, text='Status->Category map').grid(row=rr, column=1, sticky='e'); en_status_map = ttk.Entry(sf, textvariable=vals['status_map'], width=40); en_status_map.grid(row=rr, column=2, columnspan=2, sticky='we'); rr+=1
    attach_tip(en_status_map, 'Map statuses to category IDs. Example: reading=2,completed=5')
    ttk.Label(sf, text='Default category id').grid(row=rr, column=1, sticky='e'); en_status_def = ttk.Entry(sf, textvariable=vals['status_default_category'], width=10); en_status_def.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(en_status_def, 'Fallback category ID if a status has no explicit mapping.')
    cb_inc_lib = ttk.Checkbutton(sf, text='Include library statuses', variable=vals['include_library_statuses']); cb_inc_lib.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_inc_lib, 'Include all manga with a MangaDex library reading status in the processing set.')
    cb_lib_only = ttk.Checkbutton(sf, text='Library statuses only', variable=vals['library_statuses_only']); cb_lib_only.grid(row=rr, column=1, sticky='w'); rr+=1
    attach_tip(cb_lib_only, 'Process only manga with a MangaDex library status. Ignore follows and input file.')
    ttk.Label(sf, text='Assume missing status').grid(row=rr, column=1, sticky='e'); en_assume_missing = ttk.Entry(sf, textvariable=vals['assume_missing_status'], width=16); en_assume_missing.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(en_assume_missing, 'If a manga has no status on MangaDex, treat it as this status (e.g. reading).')
    cb_ps = ttk.Checkbutton(sf, text='Print status summary', variable=vals['print_status_summary']); cb_ps.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_ps, 'Print a summary of fetched statuses and mapping coverage.')
    cb_smd = ttk.Checkbutton(sf, text='Map debug', variable=vals['status_map_debug']); cb_smd.grid(row=rr, column=1, sticky='w')
    attach_tip(cb_smd, 'Verbose output for status-to-category mapping decisions.')
    cb_dbg_stat = ttk.Checkbutton(sf, text='Debug status', variable=vals['debug_status']); cb_dbg_stat.grid(row=rr, column=2, sticky='w')
    attach_tip(cb_dbg_stat, 'Print raw status dict samples after fetch.')
    cb_ser = ttk.Checkbutton(sf, text='Endpoint raw', variable=vals['status_endpoint_raw']); cb_ser.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(cb_ser, 'Dump raw JSON from /manga/status for diagnostics.')
    cb_fallback_single = ttk.Checkbutton(sf, text='Fallback per-manga', variable=vals['status_fallback_single']); cb_fallback_single.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_fallback_single, 'If bulk status returns empty, fetch each manga separately (slower).')
    ttk.Label(sf, text='Fallback throttle (s)').grid(row=rr, column=1, sticky='e'); en_fallback_throttle = ttk.Entry(sf, textvariable=vals['status_fallback_throttle'], width=8); en_fallback_throttle.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(en_fallback_throttle, 'Delay between single-status fallback calls. Default 0.3s.')
    ttk.Label(sf, text='Ignore statuses').grid(row=rr, column=1, sticky='e'); en_ignore_statuses = ttk.Entry(sf, textvariable=vals['ignore_statuses'], width=30); en_ignore_statuses.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(en_ignore_statuses, 'Statuses to ignore for mapping, comma-separated (e.g. reading)')
    ttk.Label(sf, text='Verify MD IDs (comma)').grid(row=rr, column=1, sticky='e'); en_verify_ids = ttk.Entry(sf, textvariable=vals['verify_ids'], width=40); en_verify_ids.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(en_verify_ids, 'Comma/semi-colon separated MangaDex UUIDs to verify are included.')
    ttk.Label(sf, text='Export statuses JSON').grid(row=rr, column=1, sticky='e'); en_export_statuses = ttk.Entry(sf, textvariable=vals['export_statuses'], width=40); en_export_statuses.grid(row=rr, column=2, sticky='w')
    bt_export = ttk.Button(sf, text='Browse...', command=lambda: vals['export_statuses'].set(filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON','*.json')]))); bt_export.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_export_statuses, 'Write the final statuses mapping to this file.')
    attach_tip(bt_export, 'Choose the output JSON file path.')

    r += 1

    # Read chapters
    rc = ttk.LabelFrame(fw, text='Chapter Read Sync')
    rc.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(0,6))
    rr = 0
    cb_import_read = ttk.Checkbutton(rc, text='Import read chapters (MangaDex → Suwayomi)', variable=vals['import_read']); cb_import_read.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_import_read, 'Fetch MangaDex read chapter UUIDs and mark them as read in Suwayomi (MangaDex source).')
    cb_rc_dry = ttk.Checkbutton(rc, text='Dry run', variable=vals['read_chapters_dry_run']); cb_rc_dry.grid(row=rr, column=1, sticky='w')
    attach_tip(cb_rc_dry, 'Simulate marking chapters as read without modifying Suwayomi.')
    ttk.Label(rc, text='Delay (s)').grid(row=rr, column=2, sticky='e'); en_rc_delay = ttk.Entry(rc, textvariable=vals['read_delay'], width=8); en_rc_delay.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_rc_delay, 'Wait time after adding a manga before syncing read chapters to allow chapters to populate.')
    ttk.Label(rc, text='Max requests/min').grid(row=rr, column=2, sticky='e'); en_rc_rpm = ttk.Entry(rc, textvariable=vals['max_read_requests_per_minute'], width=8); en_rc_rpm.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_rc_rpm, 'Throttle for chapter read-mark requests. Default 300.')

    # Cross-source sync options
    cb_num_fallback = ttk.Checkbutton(rc, text='Number fallback', variable=vals['read_sync_number_fallback'])
    cb_num_fallback.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_num_fallback, 'When UUIDs don\'t match, mark chapters by chapter number (for migrated entries).')
    cb_across = ttk.Checkbutton(rc, text='Across sources', variable=vals['read_sync_across_sources'])
    cb_across.grid(row=rr, column=1, sticky='w')
    attach_tip(cb_across, 'Also apply read marks to same-title entries under other sources (by chapter number) for MangaDex sync and CSV read hints.')
    cb_only_ahead = ttk.Checkbutton(rc, text='Only if ahead', variable=vals['read_sync_only_if_ahead'])
    cb_only_ahead.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(cb_only_ahead, 'Only apply read marks when the source progress is ahead of the target entry (works for MangaDex sync and CSV read hints).')

    ttk.Label(rc, text='Missing report (CSV)').grid(row=rr, column=0, sticky='w')
    en_miss = ttk.Entry(rc, textvariable=vals['missing_report'], width=50); en_miss.grid(row=rr, column=1, columnspan=2, sticky='we')
    attach_tip(en_miss, 'Write a CSV of titles where read sync is missing chapters or chapters not yet loaded (updated live).')
    bt_miss = ttk.Button(rc, text='Browse...', command=lambda: vals['missing_report'].set(filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')])))
    bt_miss.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(bt_miss, 'Choose where to save the missing-reads report.')
    r += 1
 
    # Target category
    ttk.Label(fw, text='Category ID (optional)').grid(row=r, column=0, sticky='w'); en_cat_id = ttk.Entry(fw, textvariable=vals['category_id'], width=10); en_cat_id.grid(row=r, column=1, sticky='w'); r+=1
    attach_tip(en_cat_id, 'Assign all added manga to this Suwayomi category ID (optional).')

    # CSV Import tab
    csv_tab = ttk.Frame(nb)
    nb.add(csv_tab, text='CSV Import')
    csv_tab.grid_columnconfigure(0, weight=1)
    csv_tab.grid_columnconfigure(1, weight=1)
    r = 0
    desc_csv = ttk.Frame(csv_tab); desc_csv.grid(row=r, column=0, columnspan=4, sticky='we', pady=(4, 6))
    ttk.Label(desc_csv, text='Import bookmark CSV exports (Comick, Manganato) into your Suwayomi library. Use --csv-via-mangadex to resolve titles via MangaDex.', foreground='#444').pack(side='left')
    ttk.Button(desc_csv, text='Help', width=5, command=lambda: (_save_config({**_load_config(), 'manual_find_text': 'CSV Import'}), show_manual_popup())).pack(side='right'); r += 1
    cb_csv_enable = ttk.Checkbutton(csv_tab, text='Enable CSV Import', variable=vals['csv_enabled'])
    cb_csv_enable.grid(row=r, column=0, sticky='w'); r += 1
    attach_tip(cb_csv_enable, 'When enabled, include the selected CSV files in the import pipeline. See manual: CSV Import.')

    vals['_csv_files'] = []

    csv_files_box = ttk.LabelFrame(csv_tab, text='CSV Files')
    csv_files_box.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(0, 6))
    csv_files_box.grid_columnconfigure(0, weight=1)
    csv_files_box.grid_rowconfigure(0, weight=1)

    csv_listbox = tk.Listbox(csv_files_box, height=5, selectmode='extended', exportselection=False)
    csv_listbox.grid(row=0, column=0, rowspan=4, sticky='nsew')
    csv_scroll = ttk.Scrollbar(csv_files_box, orient='vertical', command=csv_listbox.yview)
    csv_scroll.grid(row=0, column=1, rowspan=4, sticky='ns')
    csv_listbox.configure(yscrollcommand=csv_scroll.set)

    def _csv_add_files():
        paths = filedialog.askopenfilenames(title='Select CSV files', filetypes=[('CSV files', '*.csv'), ('All files', '*.*')])
        if not paths:
            return
        current = vals.get('_csv_files', [])
        changed = False
        for path in paths:
            if path and path not in current:
                current.append(path)
                csv_listbox.insert('end', path)
                changed = True
        if changed:
            root.after(0, _update_preview)

    def _csv_remove_selected():
        selection = list(csv_listbox.curselection())
        if not selection:
            return
        current = vals.get('_csv_files', [])
        for idx in reversed(selection):
            try:
                item = csv_listbox.get(idx)
            except Exception:
                continue
            csv_listbox.delete(idx)
            try:
                current.remove(item)
            except ValueError:
                pass
        root.after(0, _update_preview)

    def _csv_clear():
        vals['_csv_files'] = []
        csv_listbox.delete(0, 'end')
        root.after(0, _update_preview)

    bt_csv_add = ttk.Button(csv_files_box, text='Add...', command=_csv_add_files)
    bt_csv_add.grid(row=0, column=2, sticky='we', padx=(6, 0))
    attach_tip(bt_csv_add, 'Select one or more CSV files to include. You can add both Comick and Manganato exports.')
    bt_csv_remove = ttk.Button(csv_files_box, text='Remove Selected', command=_csv_remove_selected)
    bt_csv_remove.grid(row=1, column=2, sticky='we', padx=(6, 0), pady=(4, 0))
    attach_tip(bt_csv_remove, 'Remove the highlighted entries from the CSV list.')
    bt_csv_clear = ttk.Button(csv_files_box, text='Clear List', command=_csv_clear)
    bt_csv_clear.grid(row=2, column=2, sticky='we', padx=(6, 0), pady=(4, 0))
    attach_tip(bt_csv_clear, 'Remove all CSV files from the list.')

    r += 1
    csv_opts = ttk.LabelFrame(csv_tab, text='Options')
    csv_opts.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(0, 6))
    csv_opts.grid_columnconfigure(1, weight=1)
    rr = 0
    ttk.Label(csv_opts, text='CSV kind').grid(row=rr, column=0, sticky='w')
    cb_csv_kind = ttk.Combobox(csv_opts, textvariable=vals['csv_kind'], values=['auto', 'comick', 'manganato'], state='readonly', width=12)
    cb_csv_kind.grid(row=rr, column=1, sticky='w')
    attach_tip(cb_csv_kind, 'Force the CSV schema detection (auto by default).')
    ttk.Label(csv_opts, text='Title threshold (0..1)').grid(row=rr, column=2, sticky='e')
    en_csv_thresh = ttk.Entry(csv_opts, textvariable=vals['csv_title_threshold'], width=8)
    en_csv_thresh.grid(row=rr, column=3, sticky='w'); rr += 1
    attach_tip(en_csv_thresh, 'Similarity threshold for matching CSV titles to MangaDex (default 0.6).')

    cb_csv_strict = ttk.Checkbutton(csv_opts, text='Title strict (normalized exact only)', variable=vals['csv_title_strict'])
    cb_csv_strict.grid(row=rr, column=0, columnspan=2, sticky='w')
    attach_tip(cb_csv_strict, 'Require near-exact normalized matches instead of fuzzy matching.')
    cb_csv_prefer = ttk.Checkbutton(csv_opts, text='Prefer existing library entries', variable=vals['csv_prefer_existing'])
    cb_csv_prefer.grid(row=rr, column=2, columnspan=2, sticky='w'); rr += 1
    attach_tip(cb_csv_prefer, 'Only update CSV titles that already exist in Suwayomi; new titles from the CSV will not be added when this is checked.')

    ttk.Label(csv_opts, text='Status→Category map').grid(row=rr, column=0, sticky='w')
    en_csv_status_map = ttk.Entry(csv_opts, textvariable=vals['csv_status_to_category'], width=60)
    en_csv_status_map.grid(row=rr, column=1, columnspan=3, sticky='we'); rr += 1
    attach_tip(en_csv_status_map, 'Example: reading=2,completed=5. Applied to CSV statuses only.')

    ttk.Label(csv_opts, text='Column overrides').grid(row=rr, column=0, sticky='w')
    en_csv_colmap = ttk.Entry(csv_opts, textvariable=vals['csv_col_map'], width=60)
    en_csv_colmap.grid(row=rr, column=1, columnspan=3, sticky='we'); rr += 1
    attach_tip(en_csv_colmap, 'Override CSV column names (key=value pairs, comma-separated per entry). Use ; or newline to add multiple overrides.')

    cb_csv_progress = ttk.Checkbutton(csv_opts, text='Apply CSV read progress hints', variable=vals['csv_apply_read_progress'])
    cb_csv_progress.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_csv_progress, 'Apply last-read chapter numbers coming from the CSV directly onto matching Suwayomi entries (no MangaDex session required).')
    rr += 1

    csv_note = ttk.Label(csv_opts, text='CSV options run alongside MangaDex features. CSV rows are matched directly against your Suwayomi sources by default.', foreground='#666')
    csv_note.grid(row=rr, column=0, columnspan=4, sticky='w', pady=(4, 0))

    r += 1

    csv_statuses = ttk.LabelFrame(csv_tab, text='Statuses & Categories (optional)')
    csv_statuses.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(0, 6))
    csv_statuses.grid_columnconfigure(1, weight=1)
    rr = 0
    cb_csv_import_status = ttk.Checkbutton(csv_statuses, text='Import reading statuses (apply status map)', variable=vals['import_status'])
    cb_csv_import_status.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_csv_import_status, 'Apply status/category mapping to CSV items (and MangaDex follows when enabled).')
    ttk.Label(csv_statuses, text='Status→Category map').grid(row=rr, column=1, sticky='e')
    en_csv_status_map2 = ttk.Entry(csv_statuses, textvariable=vals['status_map'], width=40)
    en_csv_status_map2.grid(row=rr, column=2, columnspan=2, sticky='we'); rr += 1
    attach_tip(en_csv_status_map2, 'Example: reading=2,completed=5. Applies to any source that sets statuses.')
    ttk.Label(csv_statuses, text='Default category id').grid(row=rr, column=1, sticky='e')
    en_csv_status_default = ttk.Entry(csv_statuses, textvariable=vals['status_default_category'], width=10)
    en_csv_status_default.grid(row=rr, column=2, sticky='w'); rr += 1
    attach_tip(en_csv_status_default, 'Fallback category when a status has no explicit mapping.')
    cb_csv_status_summary = ttk.Checkbutton(csv_statuses, text='Print status summary', variable=vals['print_status_summary'])
    cb_csv_status_summary.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_csv_status_summary, 'Summarize mapped statuses after import.')
    cb_csv_status_debug = ttk.Checkbutton(csv_statuses, text='Map debug', variable=vals['status_map_debug'])
    cb_csv_status_debug.grid(row=rr, column=1, sticky='w')
    attach_tip(cb_csv_status_debug, 'Verbose output for status-to-category mapping decisions.')
    cb_csv_debug_status = ttk.Checkbutton(csv_statuses, text='Debug status fetch', variable=vals['debug_status'])
    cb_csv_debug_status.grid(row=rr, column=2, sticky='w')
    attach_tip(cb_csv_debug_status, 'Print raw status JSON or logs to diagnose issues.'); rr += 1

    r += 1

    # Migrate tab
    mig = ttk.Frame(nb)
    nb.add(mig, text='Migrate')
    r = 0
    # Tab description + help
    desc_m = ttk.Frame(mig); desc_m.grid(row=r, column=0, columnspan=4, sticky='we', pady=(4, 6))
    ttk.Label(desc_m, text='Migrate titles between sources within Suwayomi (find alternatives for low-chapter entries).', foreground='#444').pack(side='left')
    ttk.Button(desc_m, text='Help', width=5, command=lambda: (_save_config({**_load_config(), 'manual_find_text': 'Migration'}), show_manual_popup())).pack(side='right')
    r += 1
    cb_mig_lib = ttk.Checkbutton(mig, text='Migrate library', variable=vals['migrate_lib'])
    cb_mig_lib.grid(row=r, column=0, sticky='w'); r+=1
    attach_tip(cb_mig_lib, 'Scan your current Suwayomi library and add an alternative source for entries under a chapter threshold. Uses Title Matching settings below for source picking (when enabled). See manual: Migration > Overview')
    ttk.Label(mig, text='Threshold chapters <').grid(row=r, column=0, sticky='w'); en_mig_thresh = ttk.Entry(mig, textvariable=vals['migrate_threshold'], width=6); en_mig_thresh.grid(row=r, column=1, sticky='w'); r+=1
    attach_tip(en_mig_thresh, 'Only entries with fewer chapters than this will be considered for migration.')
    ttk.Label(mig, text='Include categories (ids/names, comma)').grid(row=r, column=0, sticky='w'); en_inc_cats = ttk.Entry(mig, textvariable=vals['migrate_include_categories'], width=50); en_inc_cats.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_inc_cats, 'Only include these categories (names or IDs), comma-separated.')
    ttk.Label(mig, text='Exclude categories (ids/names, comma)').grid(row=r, column=0, sticky='w'); en_excl_cats = ttk.Entry(mig, textvariable=vals['migrate_exclude_categories'], width=50); en_excl_cats.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_excl_cats, 'Exclude these categories (names or IDs), comma-separated.')
    ttk.Label(mig, text='Preferred sources (comma)').grid(row=r, column=0, sticky='w'); en_mig_src = ttk.Entry(mig, textvariable=vals['migrate_sources'], width=50); en_mig_src.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_mig_src, 'Comma-separated preferred alternative sources to try (name fragments). Recommended to list a few high-quality sites so migration doesn’t scan every source.')
    ttk.Label(mig, text='Exclude sources (comma)').grid(row=r, column=0, sticky='w'); en_mig_excl = ttk.Entry(mig, textvariable=vals['exclude_sources'], width=50); en_mig_excl.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_mig_excl, 'Sources to always exclude (e.g. comick,hitomi).')
    cb_pref_only = ttk.Checkbutton(mig, text='Preferred only', variable=vals['migrate_pref_only']); cb_pref_only.grid(row=r, column=0, sticky='w')
    attach_tip(cb_pref_only, 'When set with migrate sources, restrict search to only those sources.')
    cb_best = ttk.Checkbutton(mig, text='Best source', variable=vals['best_source']); cb_best.grid(row=r, column=1, sticky='w')
    attach_tip(cb_best, 'Score candidates and pick the source with the most chapters (opt-in).')
    cb_best_global = ttk.Checkbutton(mig, text='Global', variable=vals['best_global']); cb_best_global.grid(row=r, column=2, sticky='w')
    attach_tip(cb_best_global, 'Consider all languages together when scoring best source.')
    cb_best_canon = ttk.Checkbutton(mig, text='Canonical', variable=vals['best_canon']); cb_best_canon.grid(row=r, column=3, sticky='w'); r+=1
    attach_tip(cb_best_canon, 'Prefer the canonical/original language entry when scoring.')
    ttk.Label(mig, text='Best-source candidates').grid(row=r, column=0, sticky='w'); en_mig_cands = ttk.Entry(mig, textvariable=vals['best_source_candidates'], width=6); en_mig_cands.grid(row=r, column=1, sticky='w')
    attach_tip(en_mig_cands, 'Maximum candidate manga to score per title when Best source is enabled.')
    ttk.Label(mig, text='Min chapters per alt').grid(row=r, column=2, sticky='e'); en_min_alt = ttk.Entry(mig, textvariable=vals['min_chapters_per_alt'], width=6); en_min_alt.grid(row=r, column=3, sticky='w'); r+=1
    attach_tip(en_min_alt, 'Require chosen alternative to have at least this many chapters.')
    ttk.Label(mig, text='Preferred languages').grid(row=r, column=0, sticky='w'); en_pref_langs = ttk.Entry(mig, textvariable=vals['pref_langs'], width=30); en_pref_langs.grid(row=r, column=1, sticky='w')
    attach_tip(en_pref_langs, "Preferred languages (ISO codes), e.g. 'en,en-us'.")
    cb_lang_fallback = ttk.Checkbutton(mig, text='Allow non-preferred fallback', variable=vals['lang_fallback']); cb_lang_fallback.grid(row=r, column=2, sticky='w'); r+=1
    attach_tip(cb_lang_fallback, 'If preferred languages unavailable, allow other languages to be chosen.')
    ttk.Label(mig, text='Prefer sources (quality bias)').grid(row=r, column=0, sticky='w'); en_prefer_sources = ttk.Entry(mig, textvariable=vals['prefer_sources'], width=30); en_prefer_sources.grid(row=r, column=1, sticky='w')
    attach_tip(en_prefer_sources, 'Bias scoring to favor these sources if present (comma-separated).')
    ttk.Label(mig, text='Boost').grid(row=r, column=2, sticky='e'); en_prefer_boost = ttk.Entry(mig, textvariable=vals['prefer_boost'], width=6); en_prefer_boost.grid(row=r, column=3, sticky='w'); r+=1
    attach_tip(en_prefer_boost, 'Strength of the prefer-sources bias. Default 3.')
    cb_keep_both = ttk.Checkbutton(mig, text='Keep both (quality + coverage)', variable=vals['keep_both']); cb_keep_both.grid(row=r, column=0, sticky='w')
    attach_tip(cb_keep_both, 'Keep both the preferred and the alternative if they complement each other.')
    ttk.Label(mig, text='Second must have >= preferred ch.').grid(row=r, column=1, sticky='e'); en_keep_both_min = ttk.Entry(mig, textvariable=vals['keep_both_min'], width=6); en_keep_both_min.grid(row=r, column=2, sticky='w'); r+=1
    attach_tip(en_keep_both_min, 'Only keep both if the second entry has at least this many of the preferred chapters.')
    cb_remove_original = ttk.Checkbutton(mig, text='Remove original after migration (destructive)', variable=vals['remove_original'], style='Danger.TCheckbutton'); cb_remove_original.grid(row=r, column=0, sticky='w')
    attach_tip(cb_remove_original, 'Destructive: after migration, remove the original entry. Default OFF.')
    cb_remove_dup = ttk.Checkbutton(mig, text='Remove if duplicate alternative exists (destructive)', variable=vals['migrate_remove_if_duplicate'], style='Danger.TCheckbutton'); cb_remove_dup.grid(row=r, column=1, sticky='w'); r+=1
    attach_tip(cb_remove_dup, 'Destructive: if the alternative already exists, remove the original zero/low-chapter entry.')
    ttk.Label(mig, text='Filter title (optional)').grid(row=r, column=0, sticky='w'); en_filter_title = ttk.Entry(mig, textvariable=vals['filter_title'], width=50); en_filter_title.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_filter_title, 'Only process titles containing this substring.')
    ttk.Label(mig, text='Timeout (s)').grid(row=r, column=0, sticky='w'); en_timeout = ttk.Entry(mig, textvariable=vals['migrate_timeout'], width=8); en_timeout.grid(row=r, column=1, sticky='w')
    attach_tip(en_timeout, 'Per-request timeout during migration search.')
    ttk.Label(mig, text='Max sources per site').grid(row=r, column=2, sticky='e'); en_max_sources_site = ttk.Entry(mig, textvariable=vals['migrate_max_sources_per_site'], width=6); en_max_sources_site.grid(row=r, column=3, sticky='w'); r+=1
    attach_tip(en_max_sources_site, 'Limit of source candidates fetched per site (performance control).')
    cb_try_second = ttk.Checkbutton(mig, text='Try second page if no results', variable=vals['migrate_try_second_page']); cb_try_second.grid(row=r, column=0, sticky='w'); r+=1
    attach_tip(cb_try_second, 'If search returns nothing on the first page, also try page 2.')

    # Title Matching (Migration & Rehoming)
    tm = ttk.LabelFrame(mig, text='Title Matching (Migration & Rehoming)')
    tm.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(6,0))
    rr = 0
    ttk.Label(tm, text='Similarity threshold (0..1)').grid(row=rr, column=0, sticky='w')
    en_thr = ttk.Entry(tm, textvariable=vals['migrate_title_threshold'], width=6); en_thr.grid(row=rr, column=1, sticky='w')
    attach_tip(en_thr, 'Only accept candidates whose normalized title similarity meets this threshold (default 0.6).')
    cb_strict = ttk.Checkbutton(tm, text='Strict (normalized exact/containment only)', variable=vals['migrate_title_strict'])
    cb_strict.grid(row=rr, column=2, columnspan=2, sticky='w'); rr+=1
    attach_tip(cb_strict, 'Require near-exact matches of normalized titles; disables fuzzy-only matches.')
    hint_lbl = ttk.Label(tm, text='Active when either Migrate library or Rehoming is enabled.', foreground='#666')
    hint_lbl.grid(row=rr, column=0, columnspan=4, sticky='w', pady=(2,0)); rr+=1
    r += 1

    # Enable/disable Title Matching based on relevant toggles
    def _refresh_title_matching_enabled(*_a):
        active = bool(vals['migrate_lib'].get() or vals['rehoming_enabled'].get())
        try:
            en_thr.configure(state='normal' if active else 'disabled')
            cb_strict.configure(state='normal' if active else 'disabled')
            hint_lbl.configure(foreground='#666' if active else '#888')
        except Exception:
            pass

    try:
        vals['migrate_lib'].trace_add('write', _refresh_title_matching_enabled)
        vals['rehoming_enabled'].trace_add('write', _refresh_title_matching_enabled)
    except Exception:
        pass
    _refresh_title_matching_enabled()
 
    # Rehoming
    rh = ttk.LabelFrame(mig, text='Rehoming')
    rh.grid(row=r, column=0, columnspan=4, sticky='nsew', pady=(6,0))
    rr = 0
    cb_rh_en = ttk.Checkbutton(rh, text='Enable rehoming', variable=vals['rehoming_enabled']); cb_rh_en.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_rh_en, 'When a MangaDex entry has no chapters, try adding an alternative source entry instead. Uses Title Matching settings below to filter candidates.')
    ttk.Label(rh, text='Rehoming sources (comma)').grid(row=rr, column=1, sticky='e'); en_rh_src = ttk.Entry(rh, textvariable=vals['rehoming_sources'], width=40); en_rh_src.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(en_rh_src, 'Ordered list of alternative sources to try (e.g. mangasee,comick).')
    ttk.Label(rh, text='Skip if MD chapters >= ').grid(row=rr, column=0, sticky='w'); en_rh_skip = ttk.Entry(rh, textvariable=vals['rehoming_skip_ge'], width=6); en_rh_skip.grid(row=rr, column=1, sticky='w')
    attach_tip(en_rh_skip, 'If the MangaDex entry already has at least this many chapters, skip rehoming.')
    cb_rh_rm = ttk.Checkbutton(rh, text='Remove source entry after rehome (destructive)', variable=vals['rehoming_remove_mangadex'], style='Danger.TCheckbutton'); cb_rh_rm.grid(row=rr, column=2, sticky='w'); rr+=1
    attach_tip(cb_rh_rm, 'Destructive: after a successful rehome, remove the original source entry.')
 
    # Prune tab
    pr = ttk.Frame(nb)
    nb.add(pr, text='Prune')
    # Tab description + help
    desc_p = ttk.Frame(pr); desc_p.grid(row=0, column=0, columnspan=2, sticky='we', pady=(4, 6))
    ttk.Label(desc_p, text='Clean up your library by removing duplicates or entries in non-preferred languages.', foreground='#444').pack(side='left')
    # Small red warning note for destructive actions in this tab
    ttk.Label(pr, text='Warning: actions in this tab can remove entries (destructive).', foreground='#b00020').grid(row=0, column=1, sticky='e', padx=(6, 8))
    ttk.Button(desc_p, text='Help', width=5, command=lambda: (_save_config({**_load_config(), 'manual_find_text': 'Prune'}), show_manual_popup())).pack(side='right')
    r = 1
    pr.grid_columnconfigure(1, weight=1)
    cb_pr_zero = ttk.Checkbutton(pr, text='Remove zero/low-chapter duplicates (destructive)', variable=vals['prune_zero'], style='Danger.TCheckbutton'); cb_pr_zero.grid(row=r, column=0, sticky='w'); r+=1
    attach_tip(cb_pr_zero, 'Destructive: when multiple entries share a title, keep one (>= threshold) and remove the rest.')
    ttk.Label(pr, text='Keep entries with >= chapters').grid(row=r, column=0, sticky='w'); en_pr_keep = ttk.Entry(pr, textvariable=vals['prune_thresh'], width=6); en_pr_keep.grid(row=r, column=1, sticky='w'); r+=1
    attach_tip(en_pr_keep, 'Entries with chapters >= this number are considered keepers during duplicate pruning.')
    ttk.Label(pr, text='Filter by title substring').grid(row=r, column=0, sticky='w'); en_pr_filter = ttk.Entry(pr, textvariable=vals['prune_filter_title']); en_pr_filter.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_pr_filter, 'Only consider titles containing this text (case-insensitive).')
 
    # Language pruning group
    langf = ttk.LabelFrame(pr, text='Language pruning')
    langf.grid(row=r, column=0, columnspan=2, sticky='nsew', pady=(6, 0))
    langf.grid_columnconfigure(1, weight=1)
    rr = 0
    cb_pr_lang = ttk.Checkbutton(langf, text='Prune non-preferred languages (destructive)', variable=vals['prune_nonpref'], style='Danger.TCheckbutton'); cb_pr_lang.grid(row=rr, column=0, sticky='w', columnspan=3); rr+=1
    attach_tip(cb_pr_lang, 'Destructive: if another same-title entry has preferred-language chapters, remove entries without them.')
    ttk.Label(langf, text='Preferred languages').grid(row=rr, column=0, sticky='w')
    en_pr_langs = ttk.Entry(langf, textvariable=vals['pref_langs']); en_pr_langs.grid(row=rr, column=1, sticky='we', padx=(4, 4))
    attach_tip(en_pr_langs, "Comma-separated language codes to prefer, e.g. 'en,en-us'.")
    ttk.Label(langf, text='Min preferred ch.').grid(row=rr, column=2, sticky='e')
    en_pr_lang_min = ttk.Entry(langf, textvariable=vals['prune_lang_thresh'], width=6); en_pr_lang_min.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_pr_lang_min, 'Minimum preferred-language chapters to consider an entry a keeper.')
    cb_pr_keepmost = ttk.Checkbutton(pr, text='If none match, keep entry with most chapters', variable=vals['prune_keep_most']); cb_pr_keepmost.grid(row=r, column=0, sticky='w'); r+=1
    attach_tip(cb_pr_keepmost, 'When no entries have preferred-language chapters, keep only the entry with the most total chapters.')

    # Settings tab (formerly Misc)
    ms = ttk.Frame(nb)
    nb.add(ms, text='Settings')
    r = 0
    # Tab description + help
    desc_s = ttk.Frame(ms); desc_s.grid(row=r, column=0, columnspan=3, sticky='we', pady=(4, 6))
    ttk.Label(desc_s, text='General settings for the tool UI (debug output, presets).', foreground='#444').pack(side='left')
    ttk.Button(desc_s, text='Help', width=5, command=lambda: (_save_config({**_load_config(), 'manual_find_text': 'Settings'}), show_manual_popup())).pack(side='right')
    r += 1
    cb_dbg_output = ttk.Checkbutton(ms, text='Debug output', variable=vals['debug']); cb_dbg_output.grid(row=r, column=0, sticky='w'); r+=1
    attach_tip(cb_dbg_output, 'Enable verbose logging in the console for troubleshooting.')
    ttk.Label(ms, text='Preset').grid(row=r, column=0, sticky='w')
    preset_cb = ttk.Combobox(ms, textvariable=vals['preset'], values=['Prefer English Migration','Cleanup Non-English','Keep Both (Quality+Coverage)','Read Sync Across Sources'], state='readonly', width=35)
    preset_cb.grid(row=r, column=1, sticky='w')
    attach_tip(preset_cb, 'Apply a curated set of options for common workflows.')
    def _apply():
        if vals['preset'].get():
            apply_preset(vals, vals['preset'].get())
    bt_apply_preset = ttk.Button(ms, text='Apply Preset', command=_apply); bt_apply_preset.grid(row=r, column=2, sticky='w'); r+=1
    attach_tip(bt_apply_preset, 'Apply the selected preset to the current settings.')

    # Suwayomi Database tab (expanded)
    db = ttk.Frame(nb)
    nb.add(db, text='Suwayomi Database')
    r = 0
    # Tab description + help
    desc_db = ttk.Frame(db); desc_db.grid(row=r, column=0, columnspan=3, sticky='we', pady=(4, 6))
    ttk.Label(desc_db, text='Connect to Suwayomi and run general utilities (auth, list categories, open UI).', foreground='#444').pack(side='left')
    ttk.Button(desc_db, text='Help', width=5, command=lambda: (_save_config({**_load_config(), 'manual_find_text': 'Suwayomi Database'}), show_manual_popup())).pack(side='right')
    r += 1
    # Base URL moved here
    ttk.Label(db, text='Suwayomi Base URL').grid(row=r, column=0, sticky='w'); en_base = ttk.Entry(db, textvariable=vals['base_url'], width=50); en_base.grid(row=r, column=1, sticky='we'); r+=1
    attach_tip(en_base, 'Base URL of your Suwayomi server, e.g. http://127.0.0.1:4567')
    # Input file selector
    ttk.Label(db, text='Input file (txt/csv/xlsx/json/html)').grid(row=r, column=0, sticky='w')
    en_input = ttk.Entry(db, textvariable=vals['input_file'], width=50); en_input.grid(row=r, column=1, sticky='we')
    attach_tip(en_input, 'Optional: provide a bookmarks file to import (txt, csv, xlsx, json, html).')
    bt_in = ttk.Button(db, text='Browse...', command=lambda: vals['input_file'].set(filedialog.askopenfilename(filetypes=[('All supported','*.txt;*.csv;*.xlsx;*.xls;*.json;*.html;*.htm'), ('Text','*.txt;*.log;*.md'), ('JSON','*.json'), ('CSV','*.csv'), ('Excel','*.xlsx;*.xls'), ('HTML','*.html;*.htm')])));
    bt_in.grid(row=r, column=2, sticky='w'); r+=1
    attach_tip(bt_in, 'Select a bookmarks file from disk.')
 
    # Auth / connection section
    sep1 = ttk.LabelFrame(db, text='Suwayomi Authentication')
    sep1.grid(row=r, column=0, columnspan=3, sticky='nsew', pady=(8,4), padx=(0,0))
    rr = 0
    ttk.Label(sep1, text='Auth mode').grid(row=rr, column=0, sticky='w')
    cb_auth = ttk.Combobox(sep1, textvariable=vals['auth_mode'], values=['auto','basic','simple','bearer'], width=10, state='readonly'); cb_auth.grid(row=rr, column=1, sticky='w'); rr+=1
    attach_tip(cb_auth, 'Authentication strategy for Suwayomi: auto (detect), basic, simple (UI login), or bearer (API token).')
    ttk.Label(sep1, text='Username').grid(row=rr, column=0, sticky='w'); en_su_user = ttk.Entry(sep1, textvariable=vals['su_user'], width=22); en_su_user.grid(row=rr, column=1, sticky='w')
    attach_tip(en_su_user, 'Suwayomi username (for BASIC/SIMPLE)')
    ttk.Label(sep1, text='Password').grid(row=rr, column=2, sticky='w'); en_su_pass = ttk.Entry(sep1, textvariable=vals['su_pass'], show='*', width=22); en_su_pass.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_su_pass, 'Suwayomi password (for BASIC/SIMPLE)')
    ttk.Label(sep1, text='Bearer token').grid(row=rr, column=0, sticky='w'); en_su_tok = ttk.Entry(sep1, textvariable=vals['su_token'], width=50); en_su_tok.grid(row=rr, column=1, columnspan=3, sticky='we'); rr+=1
    attach_tip(en_su_tok, 'UI_LOGIN API token (Settings -> API Tokens) when using bearer auth.')
    cb_insec = ttk.Checkbutton(sep1, text='Insecure (disable TLS verify)', variable=vals['insecure']); cb_insec.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_insec, 'Disable TLS certificate verification (only if you know what you are doing).')
    ttk.Label(sep1, text='Request timeout (s)').grid(row=rr, column=2, sticky='e'); en_req_to = ttk.Entry(sep1, textvariable=vals['request_timeout'], width=8); en_req_to.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_req_to, 'HTTP request timeout for Suwayomi/MangaDex requests.')
    r += 1
 
    # Execution controls
    sep2 = ttk.LabelFrame(db, text='Execution')
    sep2.grid(row=r, column=0, columnspan=3, sticky='nsew', pady=(8,4))



    rr = 0
    cb_no_fallback = ttk.Checkbutton(sep2, text='No title fallback', variable=vals['no_title_fallback']); cb_no_fallback.grid(row=rr, column=0, sticky='w')
    attach_tip(cb_no_fallback, 'Disable MangaDex title lookup fallback when direct UUID search fails.')
   
    cb_no_prog = ttk.Checkbutton(sep2, text='No progress output', variable=vals['no_progress']); cb_no_prog.grid(row=rr, column=1, sticky='w')
    attach_tip(cb_no_prog, 'Suppress per-item progress output.')
    ttk.Label(sep2, text='Throttle (s)').grid(row=rr, column=2, sticky='e'); en_throttle = ttk.Entry(sep2, textvariable=vals['throttle'], width=8); en_throttle.grid(row=rr, column=3, sticky='w'); rr+=1
    attach_tip(en_throttle, 'Sleep seconds between processed items to avoid rate limits.')
    r += 1
 
    # Utilities
    sep3 = ttk.LabelFrame(db, text='Utilities')
    sep3.grid(row=r, column=0, columnspan=3, sticky='nsew', pady=(8,4))
    rr = 0
    cb_list_cat = ttk.Checkbutton(sep3, text='List categories (and exit)', variable=vals['list_categories']); cb_list_cat.grid(row=rr, column=0, sticky='w'); rr+=1
    attach_tip(cb_list_cat, 'Print Suwayomi categories (id + name) and exit.')
 
    def _open_suwayomi():
         url = vals['base_url'].get().strip()
         if not url:
             messagebox.showerror('Missing URL', 'Set the Suwayomi Base URL in the Misc tab first.')
             return
         try:
             webbrowser.open(url)
         except Exception as e:
             messagebox.showerror('Failed to open', str(e))
    bt_open_su = ttk.Button(sep3, text='Open Suwayomi in Browser', command=_open_suwayomi); bt_open_su.grid(row=rr, column=1, sticky='w'); rr+=1
    attach_tip(bt_open_su, 'Open the Suwayomi web UI in your default browser.')
 
    def _open_log():
         p = vals['log_path'].get().strip()
         if not p:
             messagebox.showinfo('No log path', 'Set a log path in the Misc tab first.')
             return
         path = Path(p)
         if not path.exists():
             messagebox.showinfo('Not found', f'Log file does not exist yet:\n{path}')
             return
         try:
             os.startfile(str(path))  # Windows
         except Exception:
             try:
                 webbrowser.open(path.as_uri())
             except Exception as e:
                 messagebox.showerror('Failed to open log', str(e))
    bt_open_log = ttk.Button(sep3, text='Open Log File', command=_open_log); bt_open_log.grid(row=rr, column=1, sticky='w'); rr+=1
    attach_tip(bt_open_log, 'Open the current log file path if it exists.')

    # About tab
    about = ttk.Frame(nb)
    nb.add(about, text='About')
    ar = 0
    ab_hdr = ttk.Label(about, text='Seiyomi — Suwayomi Library Manager', font=('Segoe UI', 12, 'bold'))
    ab_hdr.grid(row=ar, column=0, columnspan=3, sticky='w', padx=8, pady=(8, 4)); ar+=1
    ab_desc = ttk.Label(about, text='Seiyomi (整読み, "organize reading") — import, migrate, and clean up your Suwayomi library. MangaDex import is one of several supported workflows.', wraplength=780, justify='left')
    ab_desc.grid(row=ar, column=0, columnspan=3, sticky='w', padx=8); ar+=1
    # Environment
    try:
        import platform
        pyver = sys.version.split()[0]
        env_txt = f"Python: {pyver}  |  OS: {platform.system()} {platform.release()}  |  Executable: {sys.executable}"
    except Exception:
        env_txt = f"Python: {sys.version.split()[0]}"
    ab_env = ttk.Label(about, text=env_txt, foreground='#444')
    ab_env.grid(row=ar, column=0, columnspan=3, sticky='w', padx=8, pady=(6, 10)); ar+=1
    # Metadata (version / license / author)
    ab_meta = ttk.Label(about, text=f"Version: {APP_VERSION}    |    License: {APP_LICENSE}")
    ab_meta.grid(row=ar, column=0, columnspan=3, sticky='w', padx=8); ar+=1
    ab_author = ttk.Label(about, text=f"Author: {APP_AUTHOR}")
    ab_author.grid(row=ar, column=0, columnspan=3, sticky='w', padx=8, pady=(0, 8)); ar+=1
    # Links
    def _open_readme():
        gui_readme = Path(__file__).parent / 'GUI_README.md'
        if gui_readme.exists():
            show_markdown_popup('GUI README', gui_readme, open_external_cb=lambda: (os.startfile(str(gui_readme)) if os.name == 'nt' else webbrowser.open(gui_readme.as_uri())))
        else:
            show_readme_popup()
    def _open_manual():
        show_manual_popup()
    def _open_folder():
        folder = str(Path(__file__).parent)
        try:
            os.startfile(folder)
        except Exception:
            webbrowser.open(Path(folder).as_uri())
    def _open_repo():
        try:
            webbrowser.open(REPO_URL)
        except Exception as e:
            messagebox.showerror('Failed to open', str(e))
    def _open_license():
        p = Path(__file__).parent / 'LICENSE'
        if p.exists():
            try:
                os.startfile(str(p)) if os.name == 'nt' else webbrowser.open(p.as_uri())
            except Exception:
                webbrowser.open(p.as_uri())
        else:
            messagebox.showinfo('Not found', 'LICENSE file not found in project folder.')
    def _copy_env():
        try:
            about.clipboard_clear()
            about.clipboard_append(env_txt)
            messagebox.showinfo('Copied', 'Environment info copied to clipboard.')
        except Exception:
            pass
    ttk.Button(about, text='Open GUI README', command=_open_readme).grid(row=ar, column=0, sticky='w', padx=8)
    ttk.Button(about, text='Open Repository', command=_open_repo).grid(row=ar, column=1, sticky='w')
    ttk.Button(about, text='Open Manual', command=_open_manual).grid(row=ar, column=2, sticky='w')
    ar+=1
    ttk.Button(about, text='Open Project Folder', command=_open_folder).grid(row=ar, column=0, sticky='w', padx=8)
    ttk.Button(about, text='Open LICENSE', command=_open_license).grid(row=ar, column=1, sticky='w')
    ttk.Button(about, text='Copy Environment Info', command=_copy_env).grid(row=ar, column=2, sticky='w', pady=(6, 12))

    # Enforce tab order: Migrate, Prune, MangaDex Import, Suwayomi Database, Settings, About
    try:
        nb.insert(0, mig)
        nb.insert(1, pr)
        nb.insert(2, fw)
        nb.insert(3, csv_tab)
        nb.insert(4, db)
        nb.insert(5, ms)
        nb.insert(6, about)
    except Exception:
        pass
    nb.pack(fill='both', expand=True, padx=8, pady=(8, 4))
    try:
        nb.select(mig)
    except Exception:
        pass

    # Command Preview section
    preview_frame = ttk.LabelFrame(root, text='Command Preview')
    preview_frame.pack(fill='both', expand=False, padx=8, pady=(0, 4))
    preview_txt = tk.Text(preview_frame, height=4, wrap='word')
    preview_txt.configure(font=('Consolas', 10))
    preview_txt.pack(fill='both', expand=True, padx=6, pady=6)
    preview_txt.configure(state='disabled')

    # Bottom action row with general options
    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill='x', padx=8, pady=8)

    # Action buttons (left-aligned) and Exit (right-aligned)
    def on_run():
        if not vals['base_url'].get().strip():
            messagebox.showerror('Error', 'Base URL is required')
            return
        # Show destructive warning if needed
        try:
            cfg = _load_config()
            suppress = bool(cfg.get('suppress_destructive_warning', False))
        except Exception:
            suppress = False
        destructive_flags = []
        if vals['remove_original'].get():
            destructive_flags.append('Remove original after migration')
        if vals.get('rehoming_remove_mangadex') and vals['rehoming_remove_mangadex'].get():
            destructive_flags.append('Remove source entry after rehome')
        if vals.get('prune_zero') and vals['prune_zero'].get():
            destructive_flags.append('Prune zero/low‑chapter duplicates')
        if vals.get('prune_nonpref') and vals['prune_nonpref'].get():
            destructive_flags.append('Prune non‑preferred languages')

        if destructive_flags and not suppress:
            proceed = {'ok': False}
            dont_show = tk.BooleanVar(value=False)

            top = tk.Toplevel(root)
            top.title('Confirm destructive actions')
            top.transient(root)
            top.grab_set()
            msg = 'You are about to run actions that modify or remove entries:\n\n- ' + '\n- '.join(destructive_flags) + '\n\nThis cannot be easily undone. Proceed?'
            ttk.Label(top, text=msg, justify='left', foreground='#b00020', wraplength=520).pack(padx=12, pady=(12, 6))
            ttk.Checkbutton(top, text="Don't show this again", variable=dont_show).pack(anchor='w', padx=12, pady=(0, 8))

            btns = ttk.Frame(top); btns.pack(fill='x', padx=12, pady=(0,12))
            def _cancel():
                proceed['ok'] = False
                top.destroy()
            def _proceed():
                proceed['ok'] = True
                try:
                    cfg = _load_config()
                    if dont_show.get():
                        cfg['suppress_destructive_warning'] = True
                        _save_config(cfg)
                except Exception:
                    pass
                top.destroy()
            ttk.Button(btns, text='Cancel', command=_cancel).pack(side='right')
            ttk.Button(btns, text='Proceed', command=_proceed).pack(side='right', padx=(0,8))
            root.wait_window(top)
            if not proceed['ok']:
                return
        args = build_args(vals)
        try:
            launch_command(args, vals['save_log'].get(), vals['log_path'].get().strip() or None, vals['external_terminal'].get())
        except Exception as e:
            messagebox.showerror('Failed to launch', str(e))

    def on_reset():
        for k, var in vals.items():
            if isinstance(var, tk.BooleanVar):
                var.set(False)
            elif hasattr(var, 'set'):
                var.set('')
        vals['base_url'].set('http://127.0.0.1:4567')
        vals['dry_run'].set(True)
        vals['exclude_sources'].set('comick,hitomi')
        vals['pref_langs'].set('en,en-us')
        vals['prefer_sources'].set('asura,flame,genz,utoons')
        vals['prefer_boost'].set('3')
        vals['read_delay'].set('1')
        vals['csv_enabled'].set(False)
        vals['csv_kind'].set('auto')
        vals['csv_col_map'].set('')
        vals['csv_status_to_category'].set('')
        vals['csv_title_threshold'].set('0.6')
        vals['csv_title_strict'].set(False)
        vals['csv_apply_read_progress'].set(False)
        vals['csv_prefer_existing'].set(False)
        vals['_csv_files'] = []
        try:
            csv_listbox.delete(0, 'end')
        except Exception:
            pass
    vals['keep_both_min'].set('1')
    vals['prune_thresh'].set('1')
    vals['prune_lang_thresh'].set('1')
    # Non-destructive defaults
    vals['remove_original'].set(False)
    _render_preview()

    # Left corner: Run then Reset
    bt_run = ttk.Button(btn_frame, text='Run Script', command=on_run); bt_run.pack(side='left')
    bt_reset = ttk.Button(btn_frame, text='Reset', command=on_reset); bt_reset.pack(side='left', padx=(6, 12))
    attach_tip(bt_run, 'Execute the command as shown in the preview above.')
    attach_tip(bt_reset, 'Reset all fields to defaults.')
 
    # General toggles: Dry run + Save log + Log path (continue on the left)
    cb_dry = ttk.Checkbutton(btn_frame, text='Dry run', variable=vals['dry_run']); cb_dry.pack(side='left')
    attach_tip(cb_dry, 'Simulate actions without modifying your Suwayomi library.')
    cb_savelog = ttk.Checkbutton(btn_frame, text='Save log to file', variable=vals['save_log']); cb_savelog.pack(side='left', padx=(12, 4))
    attach_tip(cb_savelog, 'Also write console output to the chosen log file.')
    en_log = ttk.Entry(btn_frame, textvariable=vals['log_path'], width=45); en_log.pack(side='left')
    attach_tip(en_log, 'Path to save the run log (only used when Save log is checked).')
    bt_log = ttk.Button(btn_frame, text='Browse...', command=lambda: vals['log_path'].set(filedialog.asksaveasfilename(defaultextension='.log', filetypes=[('Log/Text','*.log;*.txt')]))); bt_log.pack(side='left', padx=(4, 12))
    attach_tip(bt_log, 'Choose a log file path.')
    cb_ext = ttk.Checkbutton(btn_frame, text='Open in external terminal', variable=vals['external_terminal']); cb_ext.pack(side='left')
    attach_tip(cb_ext, 'When enabled, run the command in a visible PowerShell window. Otherwise, run quietly (hidden).')
 
    # Keep Exit on the far right
    bt_exit = ttk.Button(btn_frame, text='Exit', command=root.destroy); bt_exit.pack(side='right', padx=(6, 0))
    attach_tip(bt_exit, 'Close the tool.')

    # Debounced preview update to avoid lag during rapid changes
    preview_after_id = None

    def _render_preview():
        # Build the exact command that will run
        args = build_args(vals)
        cli_exe = find_cli_executable()
        pwsh = _pwsh_binary()
        cmd_str = ''
        external = vals['external_terminal'].get()
        log_path = vals['log_path'].get().strip()
        tee_path = log_path if (vals['save_log'].get() and log_path) else None
        if cli_exe is not None:
            full_cmd = [str(cli_exe), *args]
            if external:
                ps_cmd = _build_pwsh_command(full_cmd, tee_path)
                cmd_str = f"{pwsh} -NoExit -Command \"{ps_cmd}\""
            else:
                if tee_path:
                    ps_cmd = _build_pwsh_command(full_cmd, tee_path)
                    cmd_str = f"{pwsh} -Command \"{ps_cmd}\""
                else:
                    cmd_str = ' '.join([shlex.quote(p) for p in full_cmd])
        else:
            py = python_executable()
            script = str(Path(__file__).parent / SCRIPT_NAME)
            full_cmd = [py, script, *args]
            if external:
                ps_cmd = _build_pwsh_command(full_cmd, tee_path)
                cmd_str = f"{pwsh} -NoExit -Command \"{ps_cmd}\""
            else:
                if tee_path:
                    ps_cmd = _build_pwsh_command(full_cmd, tee_path)
                    cmd_str = f"{pwsh} -Command \"{ps_cmd}\""
                else:
                    cmd_str = ' '.join([shlex.quote(p) for p in full_cmd])

        preview_txt.configure(state='normal')
        preview_txt.delete('1.0', 'end')
        preview_txt.insert('1.0', cmd_str)
        preview_txt.configure(state='disabled')

    def _update_preview():
        nonlocal preview_after_id
        try:
            if preview_after_id is not None:
                root.after_cancel(preview_after_id)
        except Exception:
            pass
        # 120 ms debounce window
        preview_after_id = root.after(120, _render_preview)

    # Trace all variables to refresh preview when they change
    for var in vals.values():
        try:
            var.trace_add('write', lambda *args: _update_preview())
        except Exception:
            pass
    _render_preview()

    root.mainloop()


if __name__ == '__main__':
    main()
