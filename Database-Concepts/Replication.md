# Replication

Replication in databases is the process of copying and maintaining data across multiple machines or nodes to improve availability, fault tolerance, read scalability, and sometimes performance.

## Master-Follower Replication

One master (leader) node accepts writes and DDL operations, and one or more follower (standby/replica) nodes replicate those changes from the master. This architecture is simple to implement since no write conflicts arise—writes only go to the master, and followers stay synchronized by replaying updates.

### Diagram

                        +--------+
                        | Client |
                        +--------+
                            |
                            v
            +-----------------------------------+
            |       Master / Leader             |
            +-----------------------------------+
              |             |                |
              v             v                v
        +------------+ +------------+ +------------+
        | Follower 1 | | Follower 2 | | Follower 3 |
        +------------+ +------------+ +------------+


## Multi-Master Replication

Multiple master (leader) nodes accept writes and DDL operations. This allows for high availability and geographic distribution of write traffic. However, since multiple nodes can process writes simultaneously, **conflict resolution** mechanisms are needed to maintain data consistency.

Follower (standby) nodes can be configured to replicate from one or more masters for read scalability and redundancy.

### Diagram

            +--------+       +--------+
            | Client |       | Client |
            +--------+       +--------+
                 |               |
                 v               v
         +----------------+  +----------------+
         | Master / Node1 |  | Master / Node2 |
         +----------------+  +----------------+
                 |               |
                 |               |
                 v               v
             +-----------------------+
             |   Conflict Resolver   |
             +-----------------------+
                       |
                       v
              +----------------+
              |  Follower Node |
              +----------------+


---

## Synchronous Replication

In **synchronous replication**, a **write transaction is not considered committed** until it has been written to one or more **follower nodes**.

- Ensures **strong consistency**
- Introduces **higher write latency**
- You can configure a **quorum** — for example, wait for 2 out of 3 followers
- Used often for banking system where consistency is more important than performance

## Asynchronous Replication

In **asynchronous replication**, a write transaction is considered committed if it is written to the master. Changes are then replicated to followers in the background.

- Enables low-latency writes
- Risk of data loss if the master fails before replication
- Often used for read scaling and performance-focused systems

## Conflict Handling in Multi-Master Replication

When multiple nodes accept writes simultaneously, **conflicts** may arise due to:

- **Concurrent updates to the same row**
- **Out-of-order transactions**
- **Schema changes occurring independently**

### Common Conflict Resolution Strategies

- **Last Write Wins (LWW)**  
  The most recent write (based on timestamp) overrides others.

- **Application-Level Logic**  
  Business rules define how conflicts are merged or rejected.

- **Custom Conflict Handlers**  
  Database extensions or middleware that automatically resolve or flag conflicts.

- **Manual Resolution**  
  Human intervention is required when automatic resolution is not safe or reliable.

## Replication Log Mechanisms

To replicate data from one node to another, databases use special logging mechanisms to track changes. These logs record what changes happen and how they should be applied on other nodes.

### 1. Write-Ahead Log (WAL) – PostgreSQL

- **WAL** is a log where all changes are recorded **before** they are written to the main database files.
- It helps with crash recovery and replication.
- PostgreSQL sends these WAL entries to follower nodes in **streaming replication**.
- Tools like `pg_basebackup` and replication slots help set up WAL-based replication.

### 2. Statement-Based Replication – MySQL

- The master logs the **actual SQL statements** it runs (like `INSERT`, `UPDATE`).
- The followers replay those same SQL statements.
- It’s simple but can be **risky** if the SQL is **non-deterministic** (e.g., `NOW()`, `UUID()`), because it may behave differently on each node.

### 3. Row-Based Replication – MySQL

- Instead of logging the SQL, this method logs the **actual rows that changed**.
- More reliable and consistent because it doesn’t depend on how the SQL was written.
- It uses more storage since full row data is logged.

### 4. Mixed-Based Replication – MySQL

- A combination of **statement-based** and **row-based** replication.
- MySQL decides automatically which one to use based on the query type.
- Gives a balance between performance and accuracy.

### 5. Trigger-Based Replication

- Custom **triggers** track changes on tables and store them in separate log or audit tables.
- An external tool or script reads those logs and applies changes to replicas.
- It’s flexible and database-agnostic, but **more complex** to manage.
- Often used in tools like **SymmetricDS** or for cross-database replication.

## Pros & Cons of Replication

### Pros

- **Horizontal Scaling**  
  Replication allows read traffic to be distributed across multiple nodes, improving scalability.

- **High Availability**  
  Replicated nodes can take over in case of failure, increasing fault tolerance.

- **Region-Based Access**  
  You can deploy read replicas in different geographic regions to serve local users with lower latency.

- **Backup & Reporting**  
  Replicas can be used for backups, analytics, or heavy read operations without impacting the primary database.

### Cons

- **Eventual Consistency**  
  In asynchronous setups, replicas may lag behind, leading to temporary inconsistencies.

- **Slower Writes (Synchronous Replication)**  
  In synchronous replication, write operations are slower due to waiting for acknowledgment from replicas.

- **Conflict Resolution (Multi-Master)**  
  Handling write conflicts and maintaining data integrity is complex in multi-master replication.

- **Operational Overhead**  
  Monitoring, failover, and ensuring data consistency across nodes add system complexity.
