import csv
import shutil
import socket
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from tkinter import ttk


APP_TITLE = "Yarche Net Eye"
REFRESH_MS = 2000


try:
    import psutil
except ImportError:
    psutil = None


@dataclass(frozen=True)
class NetworkConnection:
    pid: int | None
    process_name: str
    protocol: str
    local_address: str
    local_port: str
    remote_address: str
    remote_port: str
    status: str


def split_endpoint(endpoint: str) -> tuple[str, str]:
    endpoint = endpoint.strip()
    if not endpoint or endpoint == "*:*":
        return "", ""

    if endpoint.startswith("["):
        end = endpoint.rfind("]")
        if end != -1:
            address = endpoint[1:end]
            port = endpoint[end + 2 :] if endpoint[end + 1 : end + 2] == ":" else ""
            return address, port

    if endpoint.count(":") == 1:
        address, port = endpoint.rsplit(":", 1)
        return address, port

    if ":" in endpoint:
        address, port = endpoint.rsplit(":", 1)
        return address, port

    return endpoint, ""


def load_process_names_from_tasklist() -> dict[int, str]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell:
        try:
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-Command",
                    "Get-Process | ForEach-Object { \"{0}`t{1}\" -f $_.Id, $_.ProcessName }",
                ],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            names: dict[int, str] = {}
            for line in result.stdout.splitlines():
                pid_text, separator, process_name = line.partition("\t")
                if not separator:
                    continue
                try:
                    names[int(pid_text)] = process_name
                except ValueError:
                    continue
            if names:
                return names
        except (subprocess.SubprocessError, OSError):
            pass

    if not shutil.which("tasklist"):
        return {}

    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
            text=True,
            encoding="cp866",
            errors="replace",
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return {}

    names: dict[int, str] = {}
    for row in csv.reader(StringIO(result.stdout)):
        if len(row) < 2:
            continue
        try:
            names[int(row[1])] = row[0]
        except ValueError:
            continue

    return names


def get_connections_with_netstat() -> list[NetworkConnection]:
    if not shutil.which("netstat"):
        raise RuntimeError("Команда netstat не найдена в системе.")

    process_names = load_process_names_from_tasklist()

    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        check=True,
        text=True,
        encoding="cp866",
        errors="replace",
        timeout=8,
    )

    connections: list[NetworkConnection] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split()
        if not parts or parts[0] not in {"TCP", "UDP"}:
            continue

        protocol = parts[0]
        if protocol == "TCP" and len(parts) >= 5:
            local_address, local_port = split_endpoint(parts[1])
            remote_address, remote_port = split_endpoint(parts[2])
            status = parts[3]
            pid_text = parts[4]
        elif protocol == "UDP" and len(parts) >= 4:
            local_address, local_port = split_endpoint(parts[1])
            remote_address, remote_port = split_endpoint(parts[2])
            status = "LISTENING"
            pid_text = parts[3]
        else:
            continue

        try:
            pid = int(pid_text)
        except ValueError:
            pid = None

        connections.append(
            NetworkConnection(
                pid=pid,
                process_name=process_names.get(pid or -1, "Неизвестно"),
                protocol=protocol,
                local_address=local_address,
                local_port=local_port,
                remote_address=remote_address,
                remote_port=remote_port,
                status=status,
            )
        )

    return connections


def get_connections_with_psutil() -> list[NetworkConnection]:
    connections: list[NetworkConnection] = []
    process_cache: dict[int, str] = {}

    for connection in psutil.net_connections(kind="inet"):
        protocol = "TCP" if connection.type == socket.SOCK_STREAM else "UDP"
        local_address = connection.laddr.ip if connection.laddr else ""
        local_port = str(connection.laddr.port) if connection.laddr else ""
        remote_address = connection.raddr.ip if connection.raddr else ""
        remote_port = str(connection.raddr.port) if connection.raddr else ""
        status = connection.status if protocol == "TCP" else "LISTENING"
        pid = connection.pid

        if pid is None:
            process_name = "Система"
        elif pid in process_cache:
            process_name = process_cache[pid]
        else:
            try:
                process_name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process_name = "Недоступно"
            process_cache[pid] = process_name

        connections.append(
            NetworkConnection(
                pid=pid,
                process_name=process_name,
                protocol=protocol,
                local_address=local_address,
                local_port=local_port,
                remote_address=remote_address,
                remote_port=remote_port,
                status=status,
            )
        )

    return connections


def get_network_connections() -> tuple[list[NetworkConnection], str]:
    if psutil is not None:
        return get_connections_with_psutil(), "psutil"
    return get_connections_with_netstat(), "netstat"


class NetworkMonitorApp:
    def __init__(self, window: tk.Tk) -> None:
        self.window = window
        self.window.title(APP_TITLE)
        self.window.geometry("1180x680")
        self.window.minsize(900, 520)

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

        self.tree.column("pid", width=80, anchor="center", stretch=False)
        self.tree.column("process", width=190, anchor="w")
        self.tree.column("protocol", width=80, anchor="center", stretch=False)
        self.tree.column("local_address", width=210, anchor="w")
        self.tree.column("local_port", width=120, anchor="center", stretch=False)
        self.tree.column("remote_address", width=210, anchor="w")
        self.tree.column("remote_port", width=120, anchor="center", stretch=False)
        self.tree.column("status", width=140, anchor="center")

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
            self.rows, source = get_network_connections()
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
            hint = ""
            if source == "netstat":
                hint = " | psutil"
            self.status_var.set(
                f"Обновлено: {timestamp} | соединений: {len(self.rows)} | источник: {source}{hint}"
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
            )
            searchable = " ".join(str(value).lower() for value in values)
            if query and query not in searchable:
                continue
            self.tree.insert("", tk.END, values=values)


def main() -> None:
    if sys.platform != "win32" and psutil is None:
        print("")
        return

    window = tk.Tk()
    NetworkMonitorApp(window)
    window.mainloop()


if __name__ == "__main__":
    main()
