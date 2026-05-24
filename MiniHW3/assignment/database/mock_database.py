"""
Students: implement your own fast MockDB here.
Hint: use a Python list as your in-memory "database".

Required methods:
- add_product(name)
- remove_product(name)
- get_products() -> list[str]
"""




class MockDataBase:
    """Fast in-memory mock database for testing InventoryApp."""

    def __init__(self) -> None:
        self._products: list[str] = []

    def add_product(self, name: str) -> None:
        self._products.append(name)

    def remove_product(self, name: str) -> None:
        if name in self._products:
            self._products.remove(name)

    def get_products(self) -> list[str]:
        return list(self._products)
