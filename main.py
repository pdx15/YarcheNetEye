import hashlib
import ipaddress
import json
import socket
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import psutil
except ImportError:
    psutil = None

APP_TITLE = "Yarche Net Eye"
REFRESH_MS = 2000
BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"
LOCALES_DIR = BASE_DIR / "locales"
LOCALE_CODE = "ru"

def load_locale(locale_code: str) -> dict[str, str]:
    locale_file = LOCALES_DIR / f"{locale_code}.json"
    try:
        with locale_file.open("r", encoding="utf-8") as file:
            locale = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return locale if isinstance(locale, dict) else {}

LOCALE = load_locale(LOCALE_CODE)

def tr(key: str, **kwargs: object) -> str:
    text = LOCALE.get(key, key)
    return text.format(**kwargs) if kwargs else text

ALL_PROTOCOLS = tr("filter.protocol.all")
ALL_STATUSES = tr("filter.status.all")
STATUS_OPTIONS = (ALL_STATUSES, "ESTABLISHED", "LISTEN", "TIME_WAIT", "CLOSE_WAIT", "SYN_SENT", "UDP")
COLUMNS = {
    "pid": {"title": tr("column.pid"), "width": 80, "anchor": "center", "stretch": False},
    "process": {"title": tr("column.process"), "width": 170, "anchor": "w", "stretch": True},
    "protocol": {"title": tr("column.protocol"), "width": 70, "anchor": "center", "stretch": False},
    "local_address": {"title": tr("column.local_address"), "width": 180, "anchor": "w", "stretch": True},
    "local_port": {"title": tr("column.local_port"), "width": 110, "anchor": "center", "stretch": False},
    "remote_address": {"title": tr("column.remote_address"), "width": 180, "anchor": "w", "stretch": True},
    "remote_port": {"title": tr("column.remote_port"), "width": 110, "anchor": "center", "stretch": False},
    "status": {"title": tr("column.status"), "width": 130, "anchor": "center", "stretch": True},
    "path": {"title": tr("column.path"), "width": 260, "anchor": "w", "stretch": True},
}
CURRENT_COLUMNS = tuple(COLUMNS)
LOG_COLUMNS = ("first_seen", *CURRENT_COLUMNS)
LOG_TIME_COLUMN = {"title": tr("column.first_seen"), "width": 90, "anchor": "center", "stretch": False}

def load_settings() -> dict[str, object]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            settings = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return settings if isinstance(settings, dict) else {}

def bool_setting(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default

def text_setting(value: object, default: str, allowed: tuple[str, ...] | None = None) -> str:
    if not isinstance(value, str):
        return default
    if allowed is not None and value not in allowed:
        return default
    return value

@dataclass(frozen=True)
class NetworkConnection:
    pid: int | None
    process_name: str
    process_path: str
    protocol: str
    local_address: str
    local_port: str
    remote_address: str
    remote_port: str
    status: str

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.pid,
            self.process_name,
            self.protocol,
            self.local_address,
            self.local_port,
            self.remote_address,
            self.remote_port,
        )

@dataclass(frozen=True)
class ConnectionEvent:
    first_seen: str
    connection: NetworkConnection

def endpoint_host(endpoint: object) -> str:
    return getattr(endpoint, "ip", "") if endpoint else ""

def endpoint_port(endpoint: object) -> str:
    port = getattr(endpoint, "port", "") if endpoint else ""
    return str(port) if port != "" else ""

def is_external_address(address: str) -> bool:
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global

def get_process_info(pid: int | None, cache: dict[int, tuple[str, str]]) -> tuple[str, str]:
    if pid is None:
        return tr("process.system"), ""
    if pid == 0:
        return "System Idle Process", tr("process.system_path")
    if pid == 4:
        return "System", tr("process.system_path")
    if pid in cache:
        return cache[pid]
    try:
        process = psutil.Process(pid)
        info = (process.name(), process.exe())
    except psutil.NoSuchProcess:
        info = (tr("process.terminated"), "")
    except psutil.AccessDenied:
        try:
            info = (psutil.Process(pid).name(), tr("process.access_denied"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            info = (tr("process.unavailable"), tr("process.access_denied"))
    cache[pid] = info
    return info

def get_network_connections() -> list[NetworkConnection]:
    if psutil is None:
        raise RuntimeError(tr("error.psutil_missing_runtime"))
    rows: list[NetworkConnection] = []
    process_cache: dict[int, tuple[str, str]] = {}
    for connection in psutil.net_connections(kind="inet"):
        protocol = "TCP" if connection.type == socket.SOCK_STREAM else "UDP"
        process_name, process_path = get_process_info(connection.pid, process_cache)
        status = connection.status if protocol == "TCP" else "UDP"
        rows.append(
            NetworkConnection(
                pid=connection.pid,
                process_name=process_name,
                process_path=process_path,
                protocol=protocol,
                local_address=endpoint_host(connection.laddr),
                local_port=endpoint_port(connection.laddr),
                remote_address=endpoint_host(connection.raddr),
                remote_port=endpoint_port(connection.raddr),
                status=status or "-",
            )
        )
    return rows

class NetworkMonitorApp:
    def __init__(self, window: tk.Tk) -> None:
        self.window = window
        self.window.title(APP_TITLE)
        self.window.geometry("1360x780")
        self.window.minsize(1080, 620)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.settings = load_settings()
        filters = self.settings.get("filters", {})
        view = self.settings.get("view", {})
        columns = self.settings.get("columns", {})
        filters = filters if isinstance(filters, dict) else {}
        view = view if isinstance(view, dict) else {}
        columns = columns if isinstance(columns, dict) else {}
        self.search_var = tk.StringVar(value=text_setting(filters.get("search"), ""))
        self.protocol_filter_var = tk.StringVar(
            value=text_setting(filters.get("protocol"), ALL_PROTOCOLS, (ALL_PROTOCOLS, "TCP", "UDP"))
        )
        self.status_filter_var = tk.StringVar(
            value=text_setting(filters.get("status"), ALL_STATUSES, STATUS_OPTIONS)
        )
        self.auto_refresh_var = tk.BooleanVar(value=bool_setting(filters.get("auto_refresh"), True))
        self.external_only_var = tk.BooleanVar(value=bool_setting(filters.get("external_only"), False))
        self.with_remote_only_var = tk.BooleanVar(value=bool_setting(filters.get("with_remote_only"), False))
        self.established_only_var = tk.BooleanVar(value=bool_setting(filters.get("established_only"), False))
        self.group_by_process_var = tk.BooleanVar(value=bool_setting(view.get("group_by_process"), False))
        self.status_var = tk.StringVar(value=tr("status.ready"))
        self.column_vars = {
            column: tk.BooleanVar(value=bool_setting(columns.get(column), True))
            for column in CURRENT_COLUMNS
        }
        self.rows: list[NetworkConnection] = []
        self.events: list[ConnectionEvent] = []
        self.seen_connections: set[tuple[object, ...]] = set()
        self.current_open_groups: set[str] = set()
        self.log_open_groups: set[str] = set()
        self.baseline_loaded = False
        self.refresh_job: str | None = None
        self.build_menu()
        self.build_layout()
        self.refresh_connections()

    def build_menu(self) -> None:
        menu_bar = tk.Menu(self.window)
        settings_menu = tk.Menu(menu_bar, tearoff=False)
        fields_menu = tk.Menu(settings_menu, tearoff=False)
        for column in CURRENT_COLUMNS:
            fields_menu.add_checkbutton(
                label=COLUMNS[column]["title"],
                variable=self.column_vars[column],
                command=self.update_visible_columns,
            )
        settings_menu.add_cascade(label=tr("menu.table_fields"), menu=fields_menu)
        settings_menu.add_separator()
        settings_menu.add_command(label=tr("menu.show_all_fields"), command=self.show_all_columns)
        menu_bar.add_cascade(label=tr("menu.settings"), menu=settings_menu)
        self.window.config(menu=menu_bar)

    def build_layout(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=0)
        header = ttk.Frame(self.window, padding=(16, 14, 16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        title = ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 18, "bold"))
        title.grid(row=0, column=0, sticky="w", padx=(0, 20))
        search = ttk.Entry(header, textvariable=self.search_var)
        search.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        search.bind("<KeyRelease>", lambda _event: self.on_filter_changed())
        refresh_button = ttk.Button(header, text=tr("button.refresh"), command=self.refresh_connections)
        refresh_button.grid(row=0, column=2, padx=(0, 12))
        auto_refresh = ttk.Checkbutton(
            header,
            text=tr("filter.auto_refresh"),
            variable=self.auto_refresh_var,
            command=self.on_auto_refresh_changed,
        )
        auto_refresh.grid(row=0, column=3)
        filters = ttk.Frame(self.window, padding=(16, 0, 16, 8))
        filters.grid(row=1, column=0, sticky="ew")
        filters.columnconfigure(9, weight=1)
        ttk.Label(filters, text=tr("filter.protocol.label")).grid(row=0, column=0, sticky="w", padx=(0, 6))
        protocol_filter = ttk.Combobox(
            filters,
            textvariable=self.protocol_filter_var,
            values=(ALL_PROTOCOLS, "TCP", "UDP"),
            state="readonly",
            width=12,
        )
        protocol_filter.grid(row=0, column=1, sticky="w", padx=(0, 14))
        protocol_filter.bind("<<ComboboxSelected>>", lambda _event: self.on_filter_changed())
        ttk.Label(filters, text=tr("filter.status.label")).grid(row=0, column=2, sticky="w", padx=(0, 6))
        status_filter = ttk.Combobox(
            filters,
            textvariable=self.status_filter_var,
            values=STATUS_OPTIONS,
            state="readonly",
            width=16,
        )
        status_filter.grid(row=0, column=3, sticky="w", padx=(0, 14))
        status_filter.bind("<<ComboboxSelected>>", lambda _event: self.on_filter_changed())
        external_only = ttk.Checkbutton(
            filters,
            text=tr("filter.external_only"),
            variable=self.external_only_var,
            command=self.on_filter_changed,
        )
        external_only.grid(row=0, column=4, sticky="w", padx=(0, 14))
        with_remote_only = ttk.Checkbutton(
            filters,
            text=tr("filter.with_remote_only"),
            variable=self.with_remote_only_var,
            command=self.on_filter_changed,
        )
        with_remote_only.grid(row=0, column=5, sticky="w", padx=(0, 14))
        established_only = ttk.Checkbutton(
            filters,
            text=tr("filter.established_only"),
            variable=self.established_only_var,
            command=self.on_filter_changed,
        )
        established_only.grid(row=0, column=6, sticky="w", padx=(0, 14))
        group_by_process = ttk.Checkbutton(
            filters,
            text=tr("filter.group_by_process"),
            variable=self.group_by_process_var,
            command=self.on_view_changed,
        )
        group_by_process.grid(row=0, column=7, sticky="w", padx=(0, 14))
        reset_button = ttk.Button(filters, text=tr("button.reset_filters"), command=self.reset_filters)
        reset_button.grid(row=0, column=8, sticky="w")
        notebook = ttk.Notebook(self.window)
        notebook.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.window.rowconfigure(2, weight=1)
        current_frame = ttk.Frame(notebook)
        log_frame = ttk.Frame(notebook)
        notebook.add(current_frame, text=tr("tab.current_connections"))
        notebook.add(log_frame, text=tr("tab.new_connections_log"))
        self.current_tree = self.create_connection_table(current_frame, CURRENT_COLUMNS)
        self.log_tree = self.create_connection_table(log_frame, LOG_COLUMNS)
        self.update_visible_columns()
        footer = ttk.Frame(self.window, padding=(16, 4, 16, 14))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        status = ttk.Label(footer, textvariable=self.status_var, foreground="#4b5563")
        status.grid(row=0, column=0, sticky="w")

    def create_connection_table(self, parent: ttk.Frame, columns: tuple[str, ...]) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        tree.heading("#0", text=tr("column.group"))
        tree.column("#0", width=0, minwidth=0, stretch=False)
        for column in columns:
            config = LOG_TIME_COLUMN if column == "first_seen" else COLUMNS[column]
            tree.heading(column, text=config["title"])
            tree.column(
                column,
                width=config["width"],
                anchor=config["anchor"],
                stretch=config["stretch"],
            )
        y_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        x_scroll = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        return tree

    def show_all_columns(self) -> None:
        for variable in self.column_vars.values():
            variable.set(True)
        self.update_visible_columns()

    def update_visible_columns(self) -> None:
        visible = [column for column in CURRENT_COLUMNS if self.column_vars[column].get()]
        if not visible:
            visible = ["process"]
            self.column_vars["process"].set(True)
        self.current_tree.configure(displaycolumns=tuple(visible))
        self.log_tree.configure(displaycolumns=("first_seen", *visible))
        self.update_tree_mode()
        self.save_settings()

    def reset_filters(self) -> None:
        self.search_var.set("")
        self.protocol_filter_var.set(ALL_PROTOCOLS)
        self.status_filter_var.set(ALL_STATUSES)
        self.external_only_var.set(False)
        self.with_remote_only_var.set(False)
        self.established_only_var.set(False)
        self.on_filter_changed()

    def on_filter_changed(self) -> None:
        self.render_tables()
        self.save_settings()

    def on_auto_refresh_changed(self) -> None:
        self.schedule_refresh()
        self.save_settings()

    def on_view_changed(self) -> None:
        self.update_tree_mode()
        self.render_tables()
        self.save_settings()

    def update_tree_mode(self) -> None:
        if self.group_by_process_var.get():
            for tree in (self.current_tree, self.log_tree):
                tree.configure(show="tree headings")
                tree.column("#0", width=240, minwidth=180, stretch=False)
        else:
            for tree in (self.current_tree, self.log_tree):
                tree.configure(show="headings")
                tree.column("#0", width=0, minwidth=0, stretch=False)

    def save_settings(self) -> None:
        settings = {
            "filters": {
                "search": self.search_var.get(),
                "protocol": self.protocol_filter_var.get(),
                "status": self.status_filter_var.get(),
                "auto_refresh": self.auto_refresh_var.get(),
                "external_only": self.external_only_var.get(),
                "with_remote_only": self.with_remote_only_var.get(),
                "established_only": self.established_only_var.get(),
            },
            "view": {
                "group_by_process": self.group_by_process_var.get(),
            },
            "columns": {
                column: variable.get()
                for column, variable in self.column_vars.items()
            },
        }
        try:
            with SETTINGS_FILE.open("w", encoding="utf-8") as file:
                json.dump(settings, file, ensure_ascii=False, indent=2)
        except OSError as error:
            self.status_var.set(tr("error.save_settings", error=error))

    def close(self) -> None:
        self.save_settings()
        if self.refresh_job is not None:
            self.window.after_cancel(self.refresh_job)
            self.refresh_job = None
        self.window.destroy()

    def refresh_connections(self) -> None:
        if self.refresh_job is not None:
            self.window.after_cancel(self.refresh_job)
            self.refresh_job = None
        try:
            self.rows = get_network_connections()
            self.rows.sort(
                key=lambda item: (
                    item.process_name.lower(),
                    item.pid or 0,
                    item.protocol,
                    item.remote_address,
                    item.remote_port,
                )
            )
            new_events = self.record_new_connections(self.rows)
            self.render_tables()
            timestamp = datetime.now().strftime("%H:%M:%S")
            visible_current = len(self.filtered_connections(self.rows))
            visible_events = len(self.filtered_events(self.events))
            self.status_var.set(
                tr(
                    "status.updated",
                    timestamp=timestamp,
                    visible_current=visible_current,
                    total_current=len(self.rows),
                    new_events=new_events,
                    visible_events=visible_events,
                    total_events=len(self.events),
                )
            )
        except Exception as error:
            self.status_var.set(tr("error.read_network", error=error))
        self.schedule_refresh()

    def record_new_connections(self, rows: list[NetworkConnection]) -> int:
        identities = {row.identity for row in rows}
        if not self.baseline_loaded:
            self.seen_connections = identities
            self.baseline_loaded = True
            return 0
        new_rows = [row for row in rows if row.identity not in self.seen_connections]
        first_seen = datetime.now().strftime("%H:%M:%S")
        for row in new_rows:
            self.events.insert(0, ConnectionEvent(first_seen=first_seen, connection=row))
        self.seen_connections.update(identities)
        return len(new_rows)

    def schedule_refresh(self) -> None:
        if self.refresh_job is not None:
            self.window.after_cancel(self.refresh_job)
            self.refresh_job = None
        if self.auto_refresh_var.get():
            self.refresh_job = self.window.after(REFRESH_MS, self.refresh_connections)

    def row_matches_filters(self, row: NetworkConnection) -> bool:
        protocol_filter = self.protocol_filter_var.get()
        status_filter = self.status_filter_var.get()
        if protocol_filter != ALL_PROTOCOLS and row.protocol != protocol_filter:
            return False
        if status_filter != ALL_STATUSES and row.status != status_filter:
            return False
        if self.external_only_var.get() and not is_external_address(row.remote_address):
            return False
        if self.with_remote_only_var.get() and not row.remote_address:
            return False
        if self.established_only_var.get() and row.status != "ESTABLISHED":
            return False
        return True

    def filtered_connections(self, rows: list[NetworkConnection]) -> list[NetworkConnection]:
        query = self.search_var.get().strip().lower()
        filtered: list[NetworkConnection] = []
        for row in rows:
            if not self.row_matches_filters(row):
                continue
            values = self.connection_values(row)
            searchable = " ".join(str(value).lower() for value in values)
            if query and query not in searchable:
                continue
            filtered.append(row)
        return filtered

    def filtered_events(self, events: list[ConnectionEvent]) -> list[ConnectionEvent]:
        query = self.search_var.get().strip().lower()
        filtered: list[ConnectionEvent] = []
        for event in events:
            row = event.connection
            if not self.row_matches_filters(row):
                continue
            values = (event.first_seen, *self.connection_values(row))
            searchable = " ".join(str(value).lower() for value in values)
            if query and query not in searchable:
                continue
            filtered.append(event)
        return filtered

    def render_tables(self) -> None:
        if self.group_by_process_var.get():
            self.current_open_groups = self.read_open_groups(self.current_tree, "current")
            self.log_open_groups = self.read_open_groups(self.log_tree, "log")
        self.current_tree.delete(*self.current_tree.get_children())
        self.log_tree.delete(*self.log_tree.get_children())
        current_rows = self.filtered_connections(self.rows)
        log_events = self.filtered_events(self.events)
        if self.group_by_process_var.get():
            self.render_grouped_connections(self.current_tree, current_rows, "current", self.current_open_groups)
            self.render_grouped_events(self.log_tree, log_events, "log", self.log_open_groups)
            return
        for row in current_rows:
            self.current_tree.insert("", tk.END, values=self.connection_values(row))
        for event in log_events:
            self.log_tree.insert("", tk.END, values=(event.first_seen, *self.connection_values(event.connection)))

    def read_open_groups(self, tree: ttk.Treeview, prefix: str) -> set[str]:
        open_groups: set[str] = set()
        prefix_text = f"{prefix}:"
        for item_id in tree.get_children():
            if str(item_id).startswith(prefix_text) and tree.item(item_id, "open"):
                open_groups.add(str(item_id).removeprefix(prefix_text))
        return open_groups

    def render_grouped_connections(
        self,
        tree: ttk.Treeview,
        rows: list[NetworkConnection],
        prefix: str,
        open_groups: set[str],
    ) -> None:
        for group_key, group_rows in self.group_connections(rows).items():
            group_id = self.group_id(group_key)
            parent = tree.insert(
                "",
                tk.END,
                iid=f"{prefix}:{group_id}",
                text=self.group_title(group_key, len(group_rows)),
                values=self.group_values(group_key),
                open=group_id in open_groups,
            )
            for row in group_rows:
                tree.insert(parent, tk.END, values=self.connection_values(row))

    def render_grouped_events(
        self,
        tree: ttk.Treeview,
        events: list[ConnectionEvent],
        prefix: str,
        open_groups: set[str],
    ) -> None:
        groups: dict[tuple[object, ...], list[ConnectionEvent]] = {}
        for event in events:
            groups.setdefault(self.process_group_key(event.connection), []).append(event)
        sorted_groups = dict(
            sorted(
                groups.items(),
                key=lambda item: (str(item[0][1]).lower(), int(item[0][0]) if isinstance(item[0][0], int) else -1),
            )
        )
        for group_key, group_events in sorted_groups.items():
            group_id = self.group_id(group_key)
            parent = tree.insert(
                "",
                tk.END,
                iid=f"{prefix}:{group_id}",
                text=self.group_title(group_key, len(group_events)),
                values=("", *self.group_values(group_key)),
                open=group_id in open_groups,
            )
            for event in group_events:
                tree.insert(parent, tk.END, values=(event.first_seen, *self.connection_values(event.connection)))

    def group_connections(self, rows: list[NetworkConnection]) -> dict[tuple[object, ...], list[NetworkConnection]]:
        groups: dict[tuple[object, ...], list[NetworkConnection]] = {}
        for row in rows:
            groups.setdefault(self.process_group_key(row), []).append(row)
        return dict(
            sorted(
                groups.items(),
                key=lambda item: (str(item[0][1]).lower(), int(item[0][0]) if isinstance(item[0][0], int) else -1),
            )
        )

    def process_group_key(self, row: NetworkConnection) -> tuple[object, ...]:
        return (row.pid, row.process_name, row.process_path)

    def group_id(self, group_key: tuple[object, ...]) -> str:
        return hashlib.sha1(repr(group_key).encode("utf-8")).hexdigest()

    def group_title(self, group_key: tuple[object, ...], count: int) -> str:
        pid, process_name, _process_path = group_key
        pid_text = pid if pid is not None else "-"
        return tr("group.title", process_name=process_name, pid=pid_text, count=count)

    def group_values(self, group_key: tuple[object, ...]) -> tuple[object, ...]:
        pid, process_name, process_path = group_key
        return (
            pid if pid is not None else "-",
            process_name,
            "-",
            "-",
            "-",
            "-",
            "-",
            tr("group.status"),
            process_path or "-",
        )

    def connection_values(self, row: NetworkConnection) -> tuple[object, ...]:
        return (
            row.pid if row.pid is not None else "-",
            row.process_name,
            row.protocol,
            row.local_address or "-",
            row.local_port or "-",
            row.remote_address or "-",
            row.remote_port or "-",
            row.status,
            row.process_path or "-",
        )

def main() -> None:
    if psutil is None:
        messagebox.showerror(APP_TITLE, tr("error.psutil_missing_message"))
        return
    window = tk.Tk()
    NetworkMonitorApp(window)
    window.mainloop()

if __name__ == "__main__":
    main()
