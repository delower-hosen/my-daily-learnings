
# Transaction

A **transaction** is a way for an application to group several reads and writes into a single logical unit. Conceptually, all the operations in a transaction are executed as **one atomic operation**: either the entire transaction **succeeds** (committed) or it **fails** (aborted or rolled back). If it fails, the application can safely **retry** the transaction without side effects.

---

## Nature of Transactions

- Transactions are usually used to **change or modify** data.
- However, it's perfectly normal to have a **read-only transaction**, for example:
  - You want to generate a report based on a **consistent snapshot** of data at the time the transaction began.

---

## Transaction Lifespan

1. **BEGIN** – Start the transaction.
2. **COMMIT** – Make all changes permanent.
3. **ROLLBACK** – Undo all changes if an error or failure occurs.
4. **Unexpected failure** – Like a crash or connection loss also causes an **automatic rollback**.

---

## Example

```sql
-- Begin Transaction TX1
BEGIN;

-- Step 1: Check balance
SELECT balance FROM account WHERE id = 1;

-- Step 2: If balance > 100, transfer 100 to another account
UPDATE account SET balance = balance - 100 WHERE id = 1;
UPDATE account SET balance = balance + 100 WHERE id = 2;

-- Commit the transaction
COMMIT;
```

If any step fails, a `ROLLBACK` will ensure the database returns to the state before the transaction began.