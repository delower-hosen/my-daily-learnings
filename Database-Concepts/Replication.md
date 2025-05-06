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

## Asynchronous Replication

In **synchronous replication**, a write transaction is considered committed if it is written to the master. Changes are then replicated to followers in the background.

- Enables low-latency writes
- Risk of data loss if the master fails before replication
- Often used for read scaling and performance-focused systems