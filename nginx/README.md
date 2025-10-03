# Node.js with Nginx Load Balancing using Docker

This project demonstrates running multiple instances of a Node.js backend and load balancing them using Nginx, all connected through a Docker network.

---

## Steps

### 1. Create Docker Network
```bash
docker network create app-network
```

### 2. Node.js Backend

**server.js**
```js
const express = require('express');
const app = express();
const PORT = 3000;
const os = require("os")
const hostname = os.hostname();

app.get("/", (req, res) => {
    res.send("Hello from " + hostname )
});

app.listen(PORT, () => {
    console.log(`Server running on port ${PORT} on ${hostname}`);
});
```

**Dockerfile**
```dockerfile
# Use official Node.js LTS image
FROM node:18
# Set working directory inside container
WORKDIR /usr/src/app

# Copy package.json and package-lock.json first (for caching npm install)
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the app
COPY . .

# Start the server
CMD ["node", "server.js"]
```

### 3. Build Node.js Image
```bash
docker build -t nodeapp .
```

### 4. Run 3 Instances of Node.js and Connect to Network
```bash
docker run -d --name nodeapp1 --hostname nodeapp1 --network app-network nodeapp
docker run -d --name nodeapp2 --hostname nodeapp2 --network app-network nodeapp
docker run -d --name nodeapp3 --hostname nodeapp3 --network app-network nodeapp
```

### 5. Nginx Configuration

**nginx.conf**
```nginx
worker_processes auto;

events {
    worker_connections 1024;
}

http {
    upstream backend {
        server nodeapp1:3000;
        server nodeapp2:3000;
        server nodeapp3:3000;
    }

    server {
        listen 80;

        location /api/ {
            proxy_pass http://backend/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }
}
```

### 6. Run Nginx Container
```bash
docker run --hostname ng1 --name nginx -p 8080:80 -v H:\my-daily-learnings\nginx\app\nginx.conf:/etc/nginx/nginx.conf --network app-network -d nginx
```

### 7. Test Load Balancing
```bash
curl http://localhost:8080/api/
```

Example output:
```
Hello from nodeapp2
Hello from nodeapp3
Hello from nodeapp1
```

---

## Result
Nginx successfully load balances requests across 3 Node.js containers running in the same Docker network.