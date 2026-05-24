"""
Students: replace these placeholders with two meaningful tests.
Keep both test methods, rename if you want, and make them validate real behavior.
"""

import unittest
import tkinter as tk

from app import InventoryApp
from database.mock_database import MockDataBase;

class TestInventoryAppExtra(unittest.TestCase):

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = InventoryApp(self.root, MockDataBase())  # HINT: refactor this to use dependency injection

    def tearDown(self) -> None:
        self.root.destroy()

    def test_refresh_list(self) -> None:
        self.app.db.add_product("Apple")
        self.app.db.add_product("Banana")

        self.app.refresh_list()

        items = [
            self.app.listbox.get(i)
            for i in range(self.app.listbox.size())
        ]

        self.assertEqual(items, ["Apple", "Banana"])
        self.assertEqual(self.app.listbox.size(), 2)

    def test_empty_product_is_not_added(self) -> None:
        self.app.entry.insert(0, "   ")

        self.app.add_btn.invoke()
        self.root.update_idletasks()

        self.assertEqual(self.app.listbox.size(), 0)
        self.assertEqual(self.app.db.get_products(), [])

    if __name__ == "__main__":
        unittest.main()
