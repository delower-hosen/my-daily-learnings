
# Database Partitioning

**Database Partitioning** is a database design and optimization technique where large tables are broken down into **smaller, more manageable pieces called partitions**.  
Partitioning helps improve **query performance, manageability, and scalability** by letting the database engine decide which subset (partition) of data to access based on query conditions.

## Why Partition?
When a table grows very large:
- Queries become slow due to scanning vast amounts of data.
- Maintenance operations (vacuum, index rebuilds) become expensive.
- Managing data lifecycle (archiving, retention) becomes harder.

## Types of Partitioning

### 1. Horizontal Partitioning (Row Partitioning)
Splits **rows** into partitions based on some logic (e.g., range, list, hash).

| Example Use Case |
|------------------|
| Splitting orders table into partitions based on order date (e.g., by month or year). |

#### Example: Range Partitioning by Year
```sql
CREATE TABLE orders (
  id SERIAL,
  order_date DATE NOT NULL,
  customer_id INT,
  amount NUMERIC
) PARTITION BY RANGE (order_date);

CREATE TABLE orders_2023 PARTITION OF orders
  FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');

CREATE TABLE orders_2024 PARTITION OF orders
  FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
```

### 2. Vertical Partitioning (Column Partitioning)
Splits **columns** into separate tables. Useful for large rarely-used columns (e.g., BLOBs, JSON, documents).

| Example Use Case |
|------------------|
| Splitting customer table into two tables: one for basic info, another for profile images or documents. |

#### Example:
```sql
-- Table for frequently used data
CREATE TABLE customers_basic (
  id SERIAL PRIMARY KEY,
  name TEXT,
  email TEXT
);

-- Table for rarely accessed data
CREATE TABLE customers_profile (
  customer_id INT REFERENCES customers_basic(id),
  profile_picture BYTEA
);
```

## Partitioning Strategies

| Strategy   | Description | Example |
|------------|-------------|---------|
| **Range**  | Rows are divided into ranges of values (e.g., dates, IDs) | Partition orders by year |
| **List**   | Rows are divided into partitions by matching exact values | Partition by country code |
| **Hash**   | Rows are distributed based on hash of a column | Partition by user ID (mod 4 partitions) |

---

## Partitioning vs Sharding

| Aspect        | Partitioning                          | Sharding                                     |
|---------------|---------------------------------------|----------------------------------------------|
| Scope          | Within the same database instance     | Across multiple databases or servers         |
| Client Awareness | Transparent (DB decides partition) | Client/Router decides which shard to hit     |
| Use Case       | Manageability, performance inside same DB | Scalability across regions or large datasets |
| Analogy        | Filing cabinet with drawers           | Distributing cabinets in different offices   |

#### ✅ Real-life Analogy:
- **Partitioning** is like dividing books in a **single large bookshelf by genre**.
- **Sharding** is like having **multiple libraries in different cities**, each serving specific regions.

---

## ✅ Pros and Cons of Partitioning

### Pros
- **Faster queries**: When WHERE clause filters can target specific partitions only.
- **Efficient bulk loading and archiving**: Load data into new partitions or detach old partitions.
- **Improved maintenance**: Easier to vacuum, backup, or archive partitions individually.
- **Reduced index size per partition**: Localized indexes are smaller and faster.

### Cons
- **Complex updates**: Moving rows across partitions requires delete and insert (can fail or be slow).
- **Query pitfalls**: Poorly written queries (missing partition key) might scan all partitions.
- **Schema changes**: Might need to propagate changes to all partitions (depends on DBMS).
- **Not a magic bullet for all performance issues**.

---

## 🔥 PostgreSQL Example — Benefits of Partitioning

#### Scenario: Querying orders from 2023
```sql
EXPLAIN ANALYZE
SELECT * FROM orders WHERE order_date BETWEEN '2023-01-01' AND '2023-12-31';
```

📌 Since we used **Range Partitioning**, PostgreSQL will only scan the `orders_2023` partition — making the query much faster than scanning the entire table.

#### Bulk Archiving
You can **detach an old partition**:
```sql
ALTER TABLE orders DETACH PARTITION orders_2023;
-- Now you can archive or drop 'orders_2023' separately.
```