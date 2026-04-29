import ipaddress
import socket
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import messagebox, ttk

try:
    import psutil
except ImportError:
    psutil = None

APP_TITLE = "Yarche Net Eye"
REFRESH_MS = 2000

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
        return "Система", ""

    if pid == 0:
        return "System Idle Process", "Системный процесс"

    if pid == 4:
        return "System", "Системный процесс"

    if pid in cache:
        return cache[pid]

    try:
        process = psutil.Process(pid)
        info = (process.name(), process.exe())
    except psutil.NoSuchProcess:
        info = ("Завершен", "")
    except psutil.AccessDenied:
        try:
            info = (psutil.Process(pid).name(), "Доступ запрещен")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            info = ("Недоступно", "Доступ запрещен")

    cache[pid] = info
    return info

def get_network_connections() -> list[NetworkConnection]:
    if psutil is None:
        raise RuntimeError("Не установлен psutil. Выполните: python -m pip install -r requirements.txt")

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
        self.window.geometry("1320x760")
        self.window.minsize(1020, 600)

        self.search_var = tk.StringVar()
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.external_only_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Готово")

        self.rows: list[NetworkConnection] = []
        self.events: list[ConnectionEvent] = []
        self.seen_connections: set[tuple[object, ...]] = set()
        self.baseline_loaded = False
        self.refresh_job: str | None = None

        self.build_layout()
        self.refresh_connections()

    def build_layout(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        header = ttk.Frame(self.window, padding=(16, 14, 16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        title = ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 18, "bold"))
        title.grid(row=0, column=0, sticky="w", padx=(0, 20))

        search = ttk.Entry(header, textvariable=self.search_var)
        search.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        search.bind("<KeyRelease>", lambda _event: self.render_tables())

        refresh_button = ttk.Button(header, text="Обновить", command=self.refresh_connections)
        refresh_button.grid(row=0, column=2, padx=(0, 12))

        external_only = ttk.Checkbutton(
            header,
            text="Только внешние",
            variable=self.external_only_var,
            command=self.render_tables,
        )
        external_only.grid(row=0, column=3, padx=(0, 12))

        auto_refresh = ttk.Checkbutton(
            header,
            text="Автообновление",
            variable=self.auto_refresh_var,
            command=self.schedule_refresh,
        )
        auto_refresh.grid(row=0, column=4)

        notebook = ttk.Notebook(self.window)
        notebook.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))

        current_frame = ttk.Frame(notebook)
        log_frame = ttk.Frame(notebook)
        notebook.add(current_frame, text="Текущие соединения")
        notebook.add(log_frame, text="Журнал новых подключений")

        self.current_tree = self.create_connection_table(current_frame, include_time=False)
        self.log_tree = self.create_connection_table(log_frame, include_time=True)

        footer = ttk.Frame(self.window, padding=(16, 4, 16, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        status = ttk.Label(footer, textvariable=self.status_var, foreground="#4b5563")
        status.grid(row=0, column=0, sticky="w")

    def create_connection_table(self, parent: ttk.Frame, include_time: bool) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        columns = []
        if include_time:
            columns.append("first_seen")
        columns.extend(
            [
                "pid",
                "process",
                "protocol",
                "local_address",
                "local_port",
                "remote_address",
                "remote_port",
                "status",
                "path",
            ]
        )

        tree = ttk.Treeview(parent, columns=tuple(columns), show="headings")

        headings = {
            "first_seen": "Время",
            "pid": "PID",
            "process": "Процесс",
            "protocol": "Тип",
            "local_address": "Локальный адрес",
            "local_port": "Локальный порт",
            "remote_address": "Удаленный адрес",
            "remote_port": "Удаленный порт",
            "status": "Состояние",
            "path": "Путь",
        }
        widths = {
            "first_seen": 90,
            "pid": 80,
            "process": 170,
            "protocol": 70,
            "local_address": 180,
            "local_port": 110,
            "remote_address": 180,
            "remote_port": 110,
            "status": 130,
            "path": 260,
        }

        for column in columns:
            tree.heading(column, text=headings[column])
            anchor = "center" if column in {"first_seen", "pid", "protocol", "local_port", "remote_port", "status"} else "w"
            stretch = column not in {"first_seen", "pid", "protocol", "local_port", "remote_port"}
            tree.column(column, width=widths[column], anchor=anchor, stretch=stretch)

        y_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        x_scroll = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        return tree

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
                f"Обновлено: {timestamp} | текущих: {visible_current}/{len(self.rows)} | "
                f"новых: +{new_events} | журнал: {visible_events}/{len(self.events)}"
            )
        except Exception as error:
            self.status_var.set(f"Ошибка чтения сетевой активности: {error}")

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

    def filtered_connections(self, rows: list[NetworkConnection]) -> list[NetworkConnection]:
        query = self.search_var.get().strip().lower()
        external_only = self.external_only_var.get()
        filtered: list[NetworkConnection] = []

        for row in rows:
            if external_only and not is_external_address(row.remote_address):
                continue

            values = self.connection_values(row)
            searchable = " ".join(str(value).lower() for value in values)
            if query and query not in searchable:
                continue

            filtered.append(row)

        return filtered

    def filtered_events(self, events: list[ConnectionEvent]) -> list[ConnectionEvent]:
        query = self.search_var.get().strip().lower()
        external_only = self.external_only_var.get()
        filtered: list[ConnectionEvent] = []

        for event in events:
            row = event.connection
            if external_only and not is_external_address(row.remote_address):
                continue

            values = (event.first_seen, *self.connection_values(row))
            searchable = " ".join(str(value).lower() for value in values)
            if query and query not in searchable:
                continue

            filtered.append(event)

        return filtered

    def render_tables(self) -> None:
        self.current_tree.delete(*self.current_tree.get_children())
        for row in self.filtered_connections(self.rows):
            self.current_tree.insert("", tk.END, values=self.connection_values(row))

        self.log_tree.delete(*self.log_tree.get_children())
        for event in self.filtered_events(self.events):
            self.log_tree.insert(
                "",
                tk.END,
                values=(event.first_seen, *self.connection_values(event.connection)),
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
        messagebox.showerror(
            APP_TITLE,
            "Не установлен psutil.\n\nВыполните команду:\npython -m pip install -r requirements.txt",
        )
        return

    window = tk.Tk()
    NetworkMonitorApp(window)
    window.mainloop()

if __name__ == "__main__":
    main()
