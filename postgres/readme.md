# PostgreSQL Cheatsheet

## Docker Setup

Set up PostgreSQL and PGAdmin using Docker. PGAdmin is a web-based tool to interact with PostgreSQL visually.

### Create Docker Network
```bash
docker network create pg-network
```

### Run PostgreSQL
```bash
docker run --name my-postgres --network pg-network -v pgdata:/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=secret -p 5432:5432 -d postgres
```
This runs PostgreSQL in detached mode with a persistent volume and password.

### Run PGAdmin
```bash
docker run --name my-pgadmin --network pg-network \
  -e PGADMIN_DEFAULT_EMAIL=user@domain.com -e PGADMIN_DEFAULT_PASSWORD=secret \
  -p 15432:80 -d dpage/pgadmin4
```
Access PGAdmin at `http://localhost:15432`

### Copy SQL file into container
```bash
docker cp "C:\Users\user\Downloads\MOCK_DATA.sql" my-postgres:/tmp/MOCK_DATA.sql
```
Use `\i /tmp/MOCK_DATA.sql` inside `psql` to execute the file.

User `https://www.mockaroo.com/` to generate mock data.

### Access PostgreSQL container
```bash
docker exec -it my-postgres /bin/bash
psql -U postgres  # Enter psql shell as postgres user
```

## psql Meta-commands

Quick shell commands in `psql` (PostgreSQL interactive terminal).

| Command            | Description                                               |
| ------------------ | --------------------------------------------------------- |
| `\?`              | Show help for psql commands                               |
| `\q`              | Quit psql                                                 |
| `\l`              | List all databases                                        |
| `\c [dbname]`     | Connect to a different database                           |
| `\d`              | List all tables, views, sequences                         |
| `\dt`             | List tables only                                          |
| `\dv`             | List views only                                           |
| `\ds`             | List sequences                                            |
| `\df`             | List functions                                            |
| `\du`             | List roles/users                                          |
| `\dn`             | List schemas                                              |
| `\dp`             | Show permissions                                          |
| `\conninfo`       | Show current connection info                              |
| `\e`              | Open editor                                               |
| `\i filename`     | Execute SQL file                                          |
| `\! command`      | Run shell command                                         |
| `\timing`         | Toggle execution time display                             |
| `\x`              | Toggle expanded output                                    |

## Database & Table Operations

```sql
CREATE DATABASE test;
DROP DATABASE test;
```

### Create Table Example
```sql
CREATE TABLE person (
  id BIGSERIAL PRIMARY KEY,
  first_name VARCHAR(50) NOT NULL,
  last_name VARCHAR(50) NOT NULL,
  gender VARCHAR(7) NOT NULL,
  date_of_birth DATE NOT NULL,
  email VARCHAR(150),
  country_of_birth VARCHAR(150)
);
```

### Drop Table
```sql
DROP TABLE person;
```

## Insert & Query Data

### Insert Data
```sql
INSERT INTO person (first_name, last_name, gender, date_of_birth, email)
VALUES ('Jake', 'Jones', 'Male', DATE '1990-01-09', 'jake@gmail.com');
```

### Select Queries
```sql
SELECT * FROM person;
SELECT first_name, last_name FROM person;
SELECT * FROM person ORDER BY country_of_birth;
SELECT * FROM person ORDER BY country_of_birth DESC;
SELECT DISTINCT country_of_birth FROM person;
```

## Filtering Data

```sql
-- WHERE, AND, OR, NOT
SELECT * FROM person WHERE gender = 'Female' AND country_of_birth = 'Bangladesh';
SELECT * FROM person WHERE gender = 'Female' AND country_of_birth <> 'Bangladesh';
SELECT * FROM person WHERE gender = 'Female' AND (country_of_birth = 'Bangladesh' OR country_of_birth = 'Nepal');
```

### LIMIT & OFFSET
```sql
SELECT * FROM person LIMIT 10;
SELECT * FROM person OFFSET 5 LIMIT 10;
SELECT * FROM person OFFSET 5 FETCH FIRST 5 ROWS ONLY;
```

### IN, BETWEEN, LIKE, ILIKE
```sql
SELECT * FROM person WHERE country_of_birth IN ('Bangladesh', 'Nepal');
SELECT * FROM person WHERE email LIKE '%.com';
SELECT * FROM person WHERE email LIKE '___%.com'; -- 3 characters + .com
```

## Aggregates & Grouping

```sql
SELECT country_of_birth, COUNT(*) AS total_person
FROM person
GROUP BY country_of_birth
HAVING COUNT(*) > 70
ORDER BY country_of_birth;
```

### Common Aggregates
```sql
SELECT MIN(date_of_birth), MAX(date_of_birth), AVG(id), SUM(id) FROM person;
```

## Functions

```sql
SELECT COALESCE(email, 'Email not provided') FROM person;
SELECT NULLIF(10, 10); -- returns NULL
```

## Alter & Constraints

```sql
ALTER TABLE person DROP CONSTRAINT person_pkey;
ALTER TABLE person ADD CONSTRAINT unique_email UNIQUE(email);
ALTER TABLE person ADD CONSTRAINT chk_gender CHECK (gender IN ('Male', 'Female'));
```

## Update & Delete

```sql
UPDATE person SET email = 'hello@gmail.com' WHERE id = 1;
DELETE FROM person WHERE id = 1;
DELETE FROM person;  -- Delete all
```

## Upsert (Insert or Update)

```sql
INSERT INTO person(id, email) VALUES(1, 'a@b.com')
ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email;
```

## JOINS

### Schema Setup
```sql
CREATE TABLE car (
  id BIGSERIAL PRIMARY KEY,
  model VARCHAR(100),
  price NUMERIC(19, 2)
);

ALTER TABLE person ADD COLUMN car_id BIGINT REFERENCES car(id);
```

### Join Queries
```sql
-- Inner Join: Matches records in both tables
SELECT * FROM person JOIN car ON person.car_id = car.id;

-- Left Join: All records from left, matched from right
SELECT * FROM person LEFT JOIN car ON person.car_id = car.id;
```

## Logical SQL Execution Order

> This is the order PostgreSQL uses to evaluate SQL queries, regardless of the order you write them.

1. `FROM` – Identify source tables and perform joins
2. `WHERE` – Filter rows before grouping
3. `GROUP BY` – Group the remaining rows
4. `HAVING` – Filter groups after grouping
5. `SELECT` – Compute and return columns
6. `DISTINCT` – Remove duplicates from the result
7. `ORDER BY` – Sort the final result
8. `LIMIT / OFFSET` – Return a subset of rows