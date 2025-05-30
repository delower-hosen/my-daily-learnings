
# Docker Volumes

A **volume** in Docker is a persistent storage mechanism.  
By default, data inside a container is **ephemeral** — if the container is deleted, its data is also gone.  
Volumes allow you to store data **outside the container’s writable layer**, ensuring persistence even if the container is destroyed.

## Why Use Volumes?

- **Persistence**: Keeps data safe across container restarts, stops, deletions.
- **Sharing Data**: Multiple containers can share the same data volume.
- **Isolation from container lifecycle**: Volumes live independently from containers.
- **Performance & Security**: Optimized and more secure compared to bind mounts.
- **Easy backups, migrations, and portability.**

## Types of Volumes

### Named Volume
- Managed by Docker.
- Docker stores the data in its internal path (e.g. `/var/lib/docker/volumes/`).
- Volumes are created and tracked by Docker (`docker volume create`).
- Even if the container is stopped, deleted, or recreated — data stays safe in the volume.

### Anonymous Volume
- Automatically created if only container path is given (without a name).
- Hard to manage or reuse — generally avoided in production.

### Bind Mount
- Directly links to a specific path on the **host machine's file system**.
- Example: `/host/dir:/container/dir`.
- Preferred for development or debugging when you want to live edit files.

## Key Concepts: Where Data Lives?

| Type              | Where Data Actually Lives                              |
|-------------------|--------------------------------------------------------|
| Named Volume       | Docker manages in: `/var/lib/docker/volumes/<vol_name>/_data` |
| Bind Mount         | Whatever host directory you specify (`/host/dir`)      |

## Real-life Analogy

- **Named Volume** → Like a **USB drive managed by Docker**.  
  You plug it into any container, data remains even if you unplug the container.
- **Bind Mount** → Like **sharing a folder on your laptop directly** into the container.

## Docker Volume Lifecycle

```bash
# Create named volume
docker volume create pgdata

# Attach it to a container
docker run --name pg1 -v pgdata:/var/lib/postgresql/data postgres

# Container writes data to /var/lib/postgresql/data → saved in pgdata volume

# Stop and remove the container
docker stop pg1
docker rm pg1

# Data still exists in pgdata volume, can be reused by another container
docker run --name pg2 -v pgdata:/var/lib/postgresql/data postgres
```

### Where is the data?
It resides in:
```
/var/lib/docker/volumes/pgdata/_data
```
Docker manages this space **outside the container**, keeping it safe from container lifecycle events.

## Mount Explained (With Example)

- **Mount** simply means linking (mounting) a host storage (volume or directory) into a container’s directory.
- You can think of **mounting as connecting an external storage into your container's virtual disk space.**
- Anything the container writes to the mounted directory gets saved to the mounted volume or host path.

#### Example:
```bash
docker run --name pg1 -v pgdata:/var/lib/postgresql/data postgres
```
- Inside container → writes to `/var/lib/postgresql/data`
- Outside (on host) → saved in `/var/lib/docker/volumes/pgdata/_data`

## What If I Try To Create The Same Volume Again?
```bash
docker volume create pgdata
```
- If volume `pgdata` already exists → Docker **reuses the same volume** (safe behavior).
- Docker will not overwrite or erase existing volumes unless explicitly told to.

## Best Practices

| Use Case                          | Recommendation         |
|------------------------------------|------------------------|
| Production DB storage              | Named Volumes          |
| Development (live code editing)    | Bind Mounts            |
| Sharing data between containers    | Named Volumes          |
| Temporary scratch data (dev only)  | Anonymous Volume       |

## Handy Commands

```bash
# List all volumes
docker volume ls

# Inspect details (location, mount path)
docker volume inspect pgdata

# Remove a volume (only if unused)
docker volume rm pgdata
```
## Gotchas

- **Deleting a container does NOT delete the volume.**
- **Deleting the volume manually WILL lose the data.**
- **Always ensure no container is using a volume before deleting it.**