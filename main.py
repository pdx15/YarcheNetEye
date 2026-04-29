import tkinter as tk
from tkinter import ttk


APP_TITLE = "Yarche Net Eye"


def create_main_window() -> tk.Tk:
    window = tk.Tk()
    window.title(APP_TITLE)
    window.geometry("720x420")
    window.minsize(520, 320)

    main_frame = ttk.Frame(window, padding=32)
    main_frame.pack(fill=tk.BOTH, expand=True)

    title_label = ttk.Label(
        main_frame,
        text=APP_TITLE,
        font=("Segoe UI", 24, "bold"),
    )
    title_label.pack(pady=(40, 12))

    placeholder_label = ttk.Label(
        main_frame,
        text="Здесь будет основной интерфейс приложения.",
        font=("Segoe UI", 12),
    )
    placeholder_label.pack()

    status_label = ttk.Label(
        main_frame,
        text="Статус: основа программы создана",
        font=("Segoe UI", 10),
        foreground="#5f6b7a",
    )
    status_label.pack(side=tk.BOTTOM, pady=(24, 0))

    return window


def main() -> None:
    window = create_main_window()
    window.mainloop()


if __name__ == "__main__":
    main()
