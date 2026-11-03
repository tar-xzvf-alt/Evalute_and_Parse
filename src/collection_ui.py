"""Collection workbench. Workers communicate with Tk only via a polled queue."""

import queue
import threading
import webbrowser
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from vk_collection import (Cancelled, CollectionError, VKClient,
                           export_posts, load_profile, save_profile)
from collection_workflow import assess_groups, normalize_settings, search_groups
from ui_theme import BORDER, MUTED, TEXT, secondary


class CollectionPanel(ctk.CTkFrame):
    def __init__(self, master, token_getter, font_family):
        super().__init__(master, fg_color="transparent")
        self.token_getter = token_getter
        self.rows = []
        self.messages = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.entries = {}
        self.buttons = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(4, 12))
        ctk.CTkLabel(header, text="Региональные новости VK",
                     font=(font_family, 28, "bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Выберите источники → проверьте активность → сохраните корпус",
                     text_color=MUTED, font=(font_family, 16)).pack(anchor="w", pady=(2, 0))
        controls = ctk.CTkFrame(self, border_width=1, border_color=BORDER)
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(3, weight=1)
        fields = [("query", "Поиск сообществ", "Омск новости"),
                  ("year", "Год (границы UTC)", "2020"),
                  ("candidates", "Кандидатов в поиске (M)", "20"),
                  ("maximum", "Источников в наборе (K)", "5"),
                  ("minimum", "Минимум постов за год (N)", "100"),
                  ("min_words", "Минимум слов в тексте", "5"),
                  ("keywords", "Фразы через запятую (ИЛИ)", ""),
                  ("folder", "Папка результатов", "")]
        for index, (key, label, value) in enumerate(fields):
            row, col = divmod(index, 2)
            col *= 2
            ctk.CTkLabel(controls, text=label).grid(row=row, column=col, sticky="w", padx=(14, 8), pady=6)
            entry = ctk.CTkEntry(controls, height=34)
            entry.insert(0, value)
            entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 14), pady=6)
            self.entries[key] = entry
        self.mode = ctk.StringVar(value="Вручную")
        self.entries["year"].bind("<FocusOut>", lambda event: self.refresh())
        ctk.CTkSegmentedButton(controls, variable=self.mode,
                         values=["Вручную", "Автоматически"]).grid(row=4, column=0, padx=8, pady=8)
        self.button(controls, "Найти сообщества", self.search, primary=True, row=4, column=1)
        self.button(controls, "Выбрать папку", self.choose_folder, row=4, column=2)
        self.button(controls, "Сохранить профиль", self.save, row=4, column=3)
        self.button(controls, "Загрузить профиль", self.load, row=5, column=0)
        self.button(controls, "Оценить выбранные", self.estimate, row=5, column=1)
        self.button(controls, "Уточнить + месяцы", self.verify, row=5, column=2)
        self.button(controls, "Автоподбор заново", self.auto, row=5, column=3)

        table_frame = ctk.CTkFrame(self, border_width=1, border_color=BORDER)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        columns = ("selected", "name", "count", "coverage", "status")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  selectmode="extended", style="VK.Treeview")
        for key, title, width in zip(columns,
                                     ("Сбор", "Сообщество", "Постов за год", "Месяцы", "Статус / причина"),
                                     (60, 330, 140, 90, 260)):
            self.table.heading(key, text=title, anchor="w",
                               command=(self.sort_count if key == "count" else lambda: None))
            self.table.column(key, width=width, minwidth=50, stretch=key in ("name", "status"))
        for key in ("selected", "count", "coverage"):
            self.table.column(key, anchor="center")
        self.table.tag_configure("odd", background="#F6F8FA")
        self.table.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=(1, 0))
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.bind("<Button-1>", self.click)
        self.table.bind("<Double-1>", self.details)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=8)
        self.button(actions, "Отметить все", lambda: self.mark(True), row=0, column=0)
        self.button(actions, "Снять отметки", lambda: self.mark(False), row=0, column=1)
        self.button(actions, "Открыть VK", self.open_group, row=0, column=2)
        self.button(actions, "Собрать выбранные", self.collect, primary=True, row=0, column=3)
        self.button(actions, "Продолжить…", self.resume, row=0, column=4)
        self.stop = ctk.CTkButton(actions, text="Остановить", height=36, width=110,
                                   command=self.cancel.set, state="disabled")
        secondary(self.stop)
        self.stop.grid(row=0, column=5, padx=4)
        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.grid(row=4, column=0, sticky="ew")
        self.progress.set(0)
        self.progress.grid_remove()
        self.status = ctk.CTkLabel(self, text="Найдите сообщества или загрузите сохранённый профиль.",
                                    anchor="w", wraplength=1000, justify="left", text_color=MUTED,
                                    font=(font_family, 15))
        self.status.grid(row=5, column=0, sticky="ew", pady=6)
        self.after(100, self.poll)

    def button(self, master, text, command, primary=False, **grid):
        button = ctk.CTkButton(master, text=text, command=command, height=36)
        if not primary:
            secondary(button)
        button.grid(**grid, padx=6, pady=6, sticky="ew")
        self.buttons.append(button)

    def settings(self):
        settings = {k: widget.get().strip() for k, widget in self.entries.items()}
        settings["mode"] = self.mode.get()
        return normalize_settings(settings)

    def begin(self, operation):
        if self.busy:
            return
        try:
            settings = self.settings()
            token = self.token_getter()
            client = VKClient(token, self.cancel)
        except (ValueError, CollectionError) as error:
            messagebox.showerror("Параметры", str(error))
            return
        self.cancel.clear()
        self.busy = True
        for widget in self.buttons + list(self.entries.values()):
            widget.configure(state="disabled")
        self.stop.configure(state="normal")
        self.progress.grid()
        self.progress.start()
        self.status.configure(text="Выполняется…")

        def work():
            try:
                operation(client, settings)
            except Cancelled as error:
                self.messages.put(("status", str(error)))
            except Exception as error:
                # Exceptions from our API layer contain no credentials.
                text = str(error).replace(token, "[скрыто]") if token else str(error)
                self.messages.put(("error", text))
            finally:
                client.session.close()
                self.messages.put(("done", None))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "rows":
                    self.rows = payload
                    self.refresh()
                elif kind == "status":
                    self.status.configure(text=payload)
                elif kind == "error":
                    self.status.configure(text="Ошибка. Результат не считается полным.")
                    messagebox.showerror("Сбор VK", payload)
                elif kind == "done":
                    self.busy = False
                    self.progress.stop()
                    self.progress.set(0)
                    self.progress.grid_remove()
                    self.stop.configure(state="disabled")
                    for widget in self.buttons + list(self.entries.values()):
                        widget.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.rows):
            count = row.get("count")
            if row.get("year") != self.entries["year"].get().strip():
                count = None
            count_text = "—" if count is None else str(count)
            if count is not None and not row.get("verified"):
                count_text = "≈ " + count_text
            current = row.get("year") == self.entries["year"].get().strip()
            months = row.get("months") if current else None
            self.table.insert("", "end", iid=str(row["id"]), tags=("odd",) if index % 2 else (), values=(
                "✓" if row.get("selected") else "", row["name"], count_text,
                f"{sum(x > 0 for x in months)}/12" if months is not None else "—",
                row.get("status", "Не проверено") if current else "Не проверено для выбранного года"))

    def mark(self, value):
        if not self.busy:
            for row in self.rows:
                row["selected"] = value
            self.refresh()

    def click(self, event):
        if self.busy or self.table.identify_column(event.x) != "#1":
            return
        iid = self.table.identify_row(event.y)
        for row in self.rows:
            if str(row["id"]) == iid:
                row["selected"] = not row.get("selected")
        self.refresh()

    def details(self, event):
        iid = self.table.identify_row(event.y)
        row = next((r for r in self.rows if str(r["id"]) == iid), None)
        if row and row.get("months") is not None and row.get("year") == self.entries["year"].get().strip():
            text = "\n".join(f"{i:02d}: {n}" for i, n in enumerate(row["months"], 1))
            messagebox.showinfo(row["name"], "Публикации по месяцам (UTC):\n" + text)

    def sort_count(self):
        if not self.busy:
            self.rows.sort(key=lambda r: (-(r.get("count") if r.get("count") is not None else -1), r["id"]))
            self.refresh()

    def open_group(self):
        selected = self.table.selection()
        if selected:
            webbrowser.open("https://vk.com/club" + selected[0])

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.entries["folder"].delete(0, "end")
            self.entries["folder"].insert(0, folder)

    def search(self):
        def run(client, settings):
            rows = search_groups(client, settings)
            if settings["mode"] == "Автоматически":
                self.assess(client, settings, rows, automatic=True)
            else:
                self.messages.put(("rows", rows))
                self.messages.put(("status", f"Найдено: {len(rows)}. Отметьте источники для оценки."))
        self.begin(run)

    def assess(self, client, settings, rows, exact=False, automatic=False):
        assess_groups(client, settings, rows, exact=exact, automatic=automatic,
                      progress=lambda text: self.messages.put(("status", text)))
        self.messages.put(("rows", rows))
        self.messages.put(("status", f"Проверка завершена. Запросов API: {client.calls}. Двойной щелчок — месяцы."))

    def assess_selected(self, exact):
        import copy
        rows = copy.deepcopy(self.rows)
        chosen = [r for r in rows if r.get("selected")]
        if not chosen:
            messagebox.showinfo("Выбор", "Отметьте сообщества в столбце «Сбор».")
            return
        def run(client, settings):
            self.assess(client, settings, chosen, exact=exact)
            self.messages.put(("rows", rows))
        self.begin(run)

    def estimate(self):
        self.assess_selected(False)

    def verify(self):
        self.assess_selected(True)

    def auto(self):
        import copy
        rows = copy.deepcopy(self.rows)
        if not rows:
            messagebox.showinfo("Выбор", "Сначала найдите кандидатов или загрузите профиль.")
            return
        self.begin(lambda client, settings: self.assess(client, settings, rows, automatic=True))

    def resume(self):
        path = filedialog.askopenfilename(title="Паспорт прежнего сбора collection_*.json",
                                          filetypes=[("Паспорт сбора", "collection_*.json")])
        if path:
            self.collect(resume_manifest=path)

    def collect(self, resume_manifest=None):
        import copy
        rows = copy.deepcopy([r for r in self.rows if r.get("selected")])
        if not rows:
            messagebox.showinfo("Выбор", "Отметьте сообщества для сбора.")
            return
        def run(client, settings):
            path = export_posts(settings["folder"], rows, client, settings["year"],
                                settings["keywords"], settings["min_words"],
                                lambda name: self.messages.put(("status", "Сбор: " + name)),
                                resume_manifest=resume_manifest)
            self.messages.put(("status", "Готово. Паспорт: " + str(path)))
        self.begin(run)

    def save(self):
        try:
            settings = self.settings()
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Профиль", "*.json")])
            if path:
                save_profile(path, settings, self.rows)
        except (ValueError, OSError, CollectionError) as error:
            messagebox.showerror("Профиль", str(error))

    def load(self):
        path = filedialog.askopenfilename(filetypes=[("Профиль", "*.json")])
        if not path:
            return
        try:
            data = load_profile(path)
            for key, entry in self.entries.items():
                if key in data["settings"]:
                    entry.delete(0, "end")
                    entry.insert(0, str(data["settings"][key]))
            self.mode.set("Вручную")
            self.rows = data["groups"]
            self.refresh()
            self.status.configure(text="Набор восстановлен. Автоподбор не запускается; можно изменить год и собрать те же источники.")
        except (ValueError, KeyError, TypeError, OSError, CollectionError) as error:
            messagebox.showerror("Профиль", str(error))
