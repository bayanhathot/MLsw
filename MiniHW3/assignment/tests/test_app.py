"""
Required UI tests (empty, add, remove). Keep the changes in this file small: inject a fast fake DB
via InventoryApp(..., db=...) after you add dependency injection in app.py.
"""

import tkinter as tk
import unittest

from app import InventoryApp
from database.database import HeavyDB

class TestInventoryApp(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = InventoryApp(self.root,HeavyDB)  # HINT: refactor this to use dependency injection

    def tearDown(self) -> None:
        self.root.destroy()

    def test_initial_empty(self) -> None:
        self.assertEqual(self.app.listbox.size(), 0)

    def test_add_product(self) -> None:
        self.app.entry.insert(0, "Widget A")
        self.app.add_btn.invoke()
        self.root.update_idletasks()
        items = [self.app.listbox.get(i) for i in range(self.app.listbox.size())]
        self.assertIn("Widget A", items)

    def test_remove_product(self) -> None:
        self.app.entry.insert(0, "Widget B")
        self.app.add_btn.invoke()
        self.root.update_idletasks()
        self.assertEqual(self.app.listbox.size(), 1)
        self.app.listbox.selection_set(0)
        self.app.remove_btn.invoke()
        self.root.update_idletasks()
        self.assertEqual(self.app.listbox.size(), 0)


if __name__ == "__main__":
    unittest.main()
