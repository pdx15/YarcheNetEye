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


def endpoint_host(endpoint: object) -> str:
    return getattr(endpoint, "ip", "") if endpoint else ""


def endpoint_port(endpoint: object) -> str:
    port = getattr(endpoint, "port", "") if endpoint else ""
    return str(port) if port != "" else ""


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
        self.window.geometry("1280x720")
        self.window.minsize(980, 560)

        self.search_var = tk.StringVar()
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Готово")
        self.rows: list[NetworkConnection] = []
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
        search.bind("<KeyRelease>", lambda _event: self.render_rows())

        refresh_button = ttk.Button(header, text="Обновить", command=self.refresh_connections)
        refresh_button.grid(row=0, column=2, padx=(0, 12))

        auto_refresh = ttk.Checkbutton(
            header,
            text="Автообновление",
            variable=self.auto_refresh_var,
            command=self.schedule_refresh,
        )
        auto_refresh.grid(row=0, column=3)

        table_frame = ttk.Frame(self.window, padding=(16, 0, 16, 8))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "pid",
            "process",
            "protocol",
            "local_address",
            "local_port",
            "remote_address",
            "remote_port",
            "status",
            "path",
        )
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tree.heading("pid", text="PID")
        self.tree.heading("process", text="Процесс")
        self.tree.heading("protocol", text="Тип")
        self.tree.heading("local_address", text="Локальный адрес")
        self.tree.heading("local_port", text="Локальный порт")
        self.tree.heading("remote_address", text="Удаленный адрес")
        self.tree.heading("remote_port", text="Удаленный порт")
        self.tree.heading("status", text="Состояние")
        self.tree.heading("path", text="Путь")

        self.tree.column("pid", width=80, anchor="center", stretch=False)
        self.tree.column("process", width=170, anchor="w")
        self.tree.column("protocol", width=70, anchor="center", stretch=False)
        self.tree.column("local_address", width=180, anchor="w")
        self.tree.column("local_port", width=110, anchor="center", stretch=False)
        self.tree.column("remote_address", width=180, anchor="w")
        self.tree.column("remote_port", width=110, anchor="center", stretch=False)
        self.tree.column("status", width=130, anchor="center")
        self.tree.column("path", width=260, anchor="w")

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        footer = ttk.Frame(self.window, padding=(16, 4, 16, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        status = ttk.Label(footer, textvariable=self.status_var, foreground="#4b5563")
        status.grid(row=0, column=0, sticky="w")

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
            self.render_rows()

            timestamp = datetime.now().strftime("%H:%M:%S")
            self.status_var.set(
                f"Обновлено: {timestamp} | соединений: {len(self.rows)} | источник: psutil"
            )
        except Exception as error:
            self.status_var.set(f"Ошибка чтения сетевой активности: {error}")

        self.schedule_refresh()

    def schedule_refresh(self) -> None:
        if self.refresh_job is not None:
            self.window.after_cancel(self.refresh_job)
            self.refresh_job = None

        if self.auto_refresh_var.get():
            self.refresh_job = self.window.after(REFRESH_MS, self.refresh_connections)

    def render_rows(self) -> None:
        query = self.search_var.get().strip().lower()

        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            values = (
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
            searchable = " ".join(str(value).lower() for value in values)
            if query and query not in searchable:
                continue
            self.tree.insert("", tk.END, values=values)


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
