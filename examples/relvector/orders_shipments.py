"""End-to-end RelVector example: orders + shipments + customers in SQLite.

    python examples/relvector/orders_shipments.py                     # local sentence-transformers
    python examples/relvector/orders_shipments.py --provider hashing  # no model, lexical only

Creates a small synthetic database, inspects it, maps orders (with their shipments and
customer) to semantic records, builds a persistent index, and searches it.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from relvector import RelVector

SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, segment TEXT);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
    status TEXT NOT NULL, total REAL
);
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
    carrier TEXT, delay_reason TEXT
);
"""

CUSTOMERS = [(1, "Acme Ltd", "ops@acme.example", "wholesale"),
             (2, "Ravi Kumar", "ravi@example.com", "retail")]
ORDERS = [
    (1001, 1, "delivered", 120.0), (1002, 1, "delayed", 89.5), (1003, 2, "delayed", 42.0),
    (1004, 2, "delayed", 15.0), (1005, 1, "processing", 300.0), (1006, 2, "delayed", 77.0),
    (1007, 1, "cancelled", 10.0), (1008, 2, "delayed", 64.0),
]
SHIPMENTS = [
    (501, 1001, "DHL", None),
    (502, 1002, "FreightCo", "carrier capacity shortage"),
    (503, 1003, "UPS", "truck breakdown on the motorway"),
    (504, 1004, "FedEx", "customer requested a later delivery date"),
    (505, 1006, "Maersk", "port congestion at the destination terminal"),
    (506, 1006, "Maersk", "container held for customs inspection"),
    (507, 1008, "DHL", "payment verification pending"),
]


def build_db(path: Path) -> None:
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?)", CUSTOMERS)
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?)", ORDERS)
        conn.executemany("INSERT INTO shipments VALUES (?,?,?,?)", SHIPMENTS)
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="local", choices=["local", "hashing"])
    parser.add_argument("--workdir", default=Path(__file__).with_name("_output"), type=Path)
    args = parser.parse_args()
    args.workdir.mkdir(exist_ok=True)
    db, index = args.workdir / "shop.db", args.workdir / f"shop-{args.provider}.rvindex"
    build_db(db)
    index.unlink(missing_ok=True)

    with RelVector(f"sqlite:///{db}", embedding_provider=args.provider,
                   index_path=index) as rv:
        print("Schema:\n" + rv.inspect_schema().describe() + "\n")

        rv.configure(
            root_table="orders",
            include_tables=["shipments", "customers"],
            text_fields=["orders.status", "shipments.carrier", "shipments.delay_reason",
                         "customers.segment"],
            metadata_fields=["orders.status", "orders.total", "shipments.carrier"],
            exclude_fields=["customers.email", "customers.name"],
            templates={
                "orders": "Order {id} is {status}.",
                "shipments": "Its shipment with {carrier} reports: {delay_reason}.",
                "customers": "The customer is a {segment} account.",
            },
        )
        stats = rv.index(batch_size=3)
        print(f"Indexed: {stats}\n")

        query = "orders delayed because of transport problems"
        print(f"Query: {query!r}  (similarity is not evidence of causation)")
        for hit in rv.search(query, top_k=4, filters={"orders.status": "delayed"}):
            print(f"  {hit.score:.3f}  {hit.source_table} {hit.source_pk}  refs="
                  f"{[(r['table'], r['pk']) for r in hit.references]}")
            print(f"         {hit.text}")


if __name__ == "__main__":
    main()
