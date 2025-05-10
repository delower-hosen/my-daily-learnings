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

## Consistency

**Consistency** in the context of ACID guarantees that a transaction brings the database from one **valid state** to another. It ensures that all **integrity constraints**, **rules**, and **invariants** are upheld at the start and end of each transaction.

If any part of a transaction would result in invalid data (e.g., violating a foreign key, unique constraint, or business rule), the entire transaction is **rolled back**.

### What Does Consistency Mean?

- The application may rely on the database's atomicity and isololation to achieve consistency, but it's not up to the database alone. Thus, the letter **C** doesn't really belong in **ACID**.
- The database must always remain valid before and after a transaction.
- All constraints (e.g., data types, unique, foreign keys) and business logic must hold true.
- It does not guarantee anything about concurrent transaction interference — that’s Isolation's job.

**Example**
Assume the following constraints:
```sql
-- Account balance must never be negative
CREATE TABLE accounts (
  id INT PRIMARY KEY,
  balance NUMERIC NOT NULL CHECK (balance >= 0)
);

-- Transfer amount must be positive
CREATE TABLE transfers (
  id SERIAL PRIMARY KEY,
  from_account INT,
  to_account INT,
  amount NUMERIC CHECK (amount > 0)
);
```
```sql
-- Valid transaction (Consistent)
BEGIN;

-- Subtract from sender
UPDATE accounts SET balance = balance - 100 WHERE id = 1;

-- Add to recipient
UPDATE accounts SET balance = balance + 100 WHERE id = 2;

-- Record the transfer
INSERT INTO transfers (from_account, to_account, amount)
VALUES (1, 2, 100);

COMMIT;
```

```sql
BEGIN;

-- Attempt to overdraw account 1 (current balance is 500)
UPDATE accounts SET balance = balance - 1000 WHERE id = 1;

COMMIT;  -- ❌ Fails due to CHECK (balance >= 0)

```
> Since the balance would go negative, the database automatically rolls back to maintain consistency.

## Isolation

**Isolation** is one of the ACID properties of transactions. It ensures that **concurrent transactions** do **not interfere** with each other in a way that corrupts data or causes inconsistent reads. The level of isolation controls **what effects of one transaction are visible to another** during execution.

### Common Read & Write Phenomena

#### 1. Dirty Read

> Reading **uncommitted** changes made by another transaction.

```sql
-- TX1
BEGIN;
UPDATE accounts SET balance = 500 WHERE id = 1; -- not committed

-- TX2
SELECT balance FROM accounts WHERE id = 1; -- sees 500

-- TX1 rolls back
ROLLBACK;
```
📌 TX2 reads a value that never existed in committed state.

#### 2. Non-Repeatable Read

> Reading the **same row twice** in one transaction and getting **different values** due to a concurrent update.

```sql
-- TX1
BEGIN;
SELECT balance FROM accounts WHERE id = 1; -- gets 1000

-- TX2
BEGIN;
UPDATE accounts SET balance = 800 WHERE id = 1;
COMMIT;

-- TX1 (again)
SELECT balance FROM accounts WHERE id = 1; -- gets 800
COMMIT;
```
📌 TX1 read different values for the same row during its lifetime.

#### 3. Phantom Read

> Re-running a **range query** yields a **different set of rows** due to concurrent inserts/deletes.

```sql
-- TX1
BEGIN;
SELECT * FROM orders WHERE amount > 100; -- returns 5 rows

-- TX2
BEGIN;
INSERT INTO orders (amount) VALUES (150);
COMMIT;

-- TX1
SELECT * FROM orders WHERE amount > 100; -- now returns 6 rows
COMMIT;
```
📌 New rows appear ("phantoms") in the result set.


#### 4. Lost Update

> Two transactions read the same row, both update it, and one update gets lost.

```sql
-- TX1
BEGIN;
SELECT balance FROM accounts WHERE id = 1; -- reads 1000

-- TX2
BEGIN;
SELECT balance FROM accounts WHERE id = 1; -- also reads 1000

-- TX1
UPDATE accounts SET balance = 900 WHERE id = 1; -- subtracts 100
COMMIT;

-- TX2
UPDATE accounts SET balance = 1100 WHERE id = 1; -- adds 100
COMMIT;
```
📌 Final balance is 1100, TX1's change was lost.


## Isolation Levels

An isolation level defines how visible the changes made by one transaction are to other concurrent transactions. It helps determine how multiple transactions interact when accessing or modifying the same data.

### Types of Isolation Levels

1. **Read Uncommitted** – Can see uncommitted data from others (dirty reads).
2. **Read Committed** – Only sees committed changes from others.
3. **Repeatable Read** – Ensures rows read remain consistent for the duration.
4. **Serializable** – Fully isolated, simulates one transaction at a time.

## Isolation Levels vs Read Phenomena

| Isolation Level     | Dirty Reads | Non-Repeatable Reads | Phantom Reads | Lost Updates |
|----------------------|-------------|------------------------|----------------|----------------|
| Read Uncommitted     | ✅ Yes      | ✅ Yes                | ✅ Yes        | ✅ Yes         |
| Read Committed       | ❌ No       | ✅ Yes                | ✅ Yes        | ✅ Yes         |
| Repeatable Read      | ❌ No       | ❌ No                 | ✅ Yes        | ✅ Yes         |
| Serializable         | ❌ No       | ❌ No                 | ❌ No         | ❌ No          |