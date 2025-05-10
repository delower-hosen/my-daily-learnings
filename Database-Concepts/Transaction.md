
# Transactions in Databases

A **transaction** is a way for an application to group several reads and writes into a single logical unit. Conceptually, all the operations in a transaction are executed as **one atomic operation**: either the entire transaction **succeeds** (committed) or it **fails** (aborted or rolled back). If it fails, the application can safely **retry** the transaction without side effects.

## Nature of Transactions

- Most transactions are used to **modify data** (e.g., update, insert, delete).
- However, you can also perform **read-only transactions** if you want:
  - For example, generating a report based on a consistent snapshot of the database.

## Transaction Lifespan

1. **BEGIN** – Start the transaction.
2. **COMMIT** – Apply and persist all changes.
3. **ROLLBACK** – Undo all changes if an error or failure occurs.
4. **Unexpected termination** – Crash or disconnect causes **automatic rollback**.

## Transaction Example

```sql
-- Transfer $100 from Account 1 to Account 2
BEGIN;

-- Step 1: Read balance
SELECT balance FROM account WHERE id = 1;

-- Step 2: Perform transfer if balance is sufficient
UPDATE account SET balance = balance - 100 WHERE id = 1;
UPDATE account SET balance = balance + 100 WHERE id = 2;

-- Step 3: Commit the transaction
COMMIT;
```

If any of the steps fail (e.g., network issue or constraint violation), a **ROLLBACK** ensures the database returns to its previous state.

## ACID Properties of Transactions

The reliability of database transactions is ensured by the **ACID** properties:

| Property     | Meaning                                              |
|--------------|------------------------------------------------------|
| Atomicity    | All operations succeed or none do.                   |
| Consistency  | The database stays valid after the transaction.      |
| Isolation    | Transactions don't interfere with each other.        |
| Durability   | Committed changes persist, even after a crash.       |

### Atomicity

- A transaction is all-or-nothing.
- If any part of a transaction fails, **no changes** are made permanent.
- Even if some operations succeed, they are **rolled back** on failure.
- If a crash occurs before `COMMIT`, the whole transaction is **discarded**.

> 💡 A more intuitive term might be **Abortability**, as the key feature is the ability to cancel the entire transaction.

**Example:**

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
-- If any update fails, the transaction is rolled back
COMMIT;
```
