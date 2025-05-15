
# Basic Docker Commands Cheat Sheet

This cheat sheet includes essential Docker commands with simple descriptions.

## Docker Images

`docker pull <image>` Download an image from docker hub.

| Command | Description |
|---------|-------------|
| `docker pull <image>` | Download an image from Docker Hub |
| `docker images` | List all downloaded images |
| `docker rmi <image>` | Remove an image from local storage |
| `docker rm -f $(docker ps -a -q)` | Remove all images by force

## Docker Containers

| Command | Description |
|---------|-------------|
| `docker run <image>` | Run a container from an image |
| `docker run --name my-container-name -d <image>` | -d runs container in detached mode, --name for container name |
| `docker run -it <image> /bin/bash` | Run container in interactive mode with terminal |
| `docker ps` | List running containers |
| `docker ps -a` | List all containers (including stopped ones) |
| `docker stop <container>` | Stop a running container |
| `docker rm <container>` | Remove a stopped container |
| `docker rm -f $(docker ps -a -q)` | Remove all containers
| `docker exec -it <container> /bin/bash` | Execute command inside a running container |

## Ports and Volumes

| Command | Description |
|---------|-------------|
| `docker run -p <host_port>:<container_port> <image>` | Run container exposing port |
| `docker run -v <host_dir>:<container_dir> <image>` | Run container with volume mount |

## Docker Networks

| Command | Description |
|---------|-------------|
| `docker network ls` | List all Docker networks |
| `docker network create <name>` | Create a new Docker network |
| `docker network inspect <name>` | Inspect network details |

## Docker System and Cleanup

| Command | Description |
|---------|-------------|
| `docker system prune` | Clean up unused data (images, containers, volumes, networks) |
| `docker volume prune` | Clean up unused volumes |
| `docker image prune` | Clean up dangling images |

## Docker Compose

| Command | Description |
|---------|-------------|
| `docker compose up` | Start services defined in `docker-compose.yml` |
| `docker compose down` | Stop and remove containers, networks created by Compose |


## Notes

- Use `docker inspect <container_or_image>` to see detailed metadata.
- Use `docker logs <container>` to view container logs.
- Use `docker stats` to see real-time resource usage.

## Example

```bash
# Run PostgreSQL with:
# - container name (--name)
# - environment variable for password (-e)
# - exposed port (-p)
# - detached mode (-d)
docker run --name my-postgres -e POSTGRES_PASSWORD=secret -p 5432:5432 -d postgres

# Run PGAdmin with:
# - container name
# - email and password env variables
# - exposed port
# - detached mode
docker run --name my-pgadmin -e PGADMIN_DEFAULT_EMAIL=user@domain.com -e PGADMIN_DEFAULT_PASSWORD=secret -p 8080:80 -d dpage/pgadmin4