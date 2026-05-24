import tkinter as tk
from tkinter import ttk

import database.mock_database
from database.database import HeavyDB


class InventoryApp:
    """Tkinter inventory UI"""

    def __init__(self, root: tk.Tk,db = None) -> None:
        self.root = root
        self.db = db if db is not None else HeavyDB()

        main = ttk.Frame(root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        self.entry = ttk.Entry(main, width=32)
        self.entry.pack(fill=tk.X, pady=(0, 4))

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        self.add_btn = ttk.Button(btn_row, text="add", command=self._on_add)
        self.add_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.remove_btn = ttk.Button(btn_row, text="Remove", command=self._on_remove)
        self.remove_btn.pack(side=tk.LEFT)

        self.listbox = tk.Listbox(main, height=10, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.status_var).pack(fill=tk.X, pady=(4, 0))

        self.refresh_list()

    def refresh_list(self) -> None:
        self.listbox.delete(0, tk.END)
        for name in self.db.get_products():
            self.listbox.insert(tk.END, name)

    def _on_add(self) -> None:
        name = self.entry.get().strip()
        if not name:
            return
        self._set_waiting(True)
        self.db.add_product(name)
        self.entry.delete(0, tk.END)
        self.refresh_list()
        self._set_waiting(False)

    def _on_remove(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        self._set_waiting(True)
        self.db.remove_product(name)
        self.refresh_list()
        self._set_waiting(False)

    def _set_waiting(self, waiting: bool) -> None:
        self.status_var.set("Waiting for response from database..." if waiting else "")
        self.root.update_idletasks()


if __name__ == "__main__":
    r = tk.Tk()
    r.title("InventoryManager v1.0")
    InventoryApp(r)
    r.mainloop()
    r.mainloop()
