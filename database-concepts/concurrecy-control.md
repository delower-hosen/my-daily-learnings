# Shared Lock vs Exclusive Lock

In database concurrency control, **locks** are mechanisms to manage **concurrent access to data**, ensuring **consistency** and preventing **conflicts**.

## Shared Lock (S-Lock)
- Allows **multiple transactions to read** the same data **concurrently**.
- **Prevents writing** while the lock is held.
- Other transactions **can acquire shared locks simultaneously**, but **cannot write** until all shared locks are released.

### Example:
```sql
-- TX1 starts
BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR SHARE;
-- TX2 starts
BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR SHARE;
-- ✅ Both TX1 and TX2 can read at the same time.

-- ❌ Any attempt to UPDATE/DELETE this row will wait or fail until locks are released.
```

---

## Exclusive Lock (X-Lock)
- **Only one transaction can hold an exclusive lock** at a time.
- **Prevents both read and write** by others.
- Others must **wait until the exclusive lock is released**.

### Example:
```sql
-- TX1 starts
BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR UPDATE;
-- This acquires EXCLUSIVE lock on the row.

-- TX2 starts
BEGIN;
SELECT * FROM accounts WHERE id = 1 FOR SHARE;
-- ❌ TX2 will be blocked until TX1 commits or rolls back.
```