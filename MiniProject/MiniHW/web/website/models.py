class ProductModel:
    """
    Wrapper around a PyMongo "products" collection
    using the product name as the unique primary key.
    """

    def __init__(self, collection):
        """
        :param collection: a PyMongo Collection (e.g. mongo.db.
        products)
        """
        self.collection = collection
        # ensure "name" is used as the _id and is unique
        # (MongoDB enforces uniqueness on _id automatically)

    def insert(self, name: str, price: float):
        """
        Insert a product document using "name" as the _id.
        Raises DuplicateKeyError if a product with the same name
        already exists.
        Returns the name (which is the _id).
        """
        doc = {
        "_id": name, # primary key
        "price": price
        }
        result = self.collection.insert_one(doc)
        return result.inserted_id # will be the same as "name"

    def all(self):
        """
        Return a list of all products as dicts with "name" and "
        price".
        """
        # project _id to "name"
        cursor = self.collection.find({}, {"price": 1})
        return [{"name": doc["_id"], "price": doc["price"]} for
        doc in cursor]

    def remove(self, name: str):
        """
        Remove a product by its name (_id).
        Returns the number of deleted documents (0 or 1).
        """
        result = self.collection.delete_one({"_id": name})
        return result.deleted_count