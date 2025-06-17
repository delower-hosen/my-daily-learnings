# Push, Short Poll, Long Poll

These are patterns for client-server communication where the client wants to receive updates from the server.

## Push (Server Push / WebSockets / SSE)

**What it is:**  
- The client establishes a persistent connection to the server.
- The server actively sends updates to the client as they happen.
- The client doesn't have to request anything
- Requires a protocol that supports bidirectional or unidirectional server-to-client streaming (e.g., WebSockets, SSE).
- Used by rabbitmq

**Examples:**  
- WebSockets (bidirectional)  
- Server-Sent Events (unidirectional) 
- RabbitMQ consumers
- Live chat, multiplayer games, stock dashboards

**Pros:**  
- Real-time updates  
- Efficient (no repeated requests)  

**Cons:**  
- Client must be online
- Requires a biderectional protocol
- Client might not be able to handle

## Short Poll (Frequent Polling)

**What it is:**  
- The client sends repeated short-lived requests asking, _"Any updates?"_. 
- The server responds immediately with a handle
- The server continues to process the request
- The client uses that handle to check status
- Multiple "short" request response as polls 

**Examples:**  
- Early chat apps  
- Basic notification systems  

**Pros:**  
- Simple to implement  
- Works over standard HTTP  

**Cons:**  
- High server load  
- Wastes bandwidth  
- Latency tied to polling interval  

## Long Poll (HTTP Long Polling)

**What it is:**  
- The client sends request.
- The server responds immediately with a handle
- The server continues to process the request
- The client uses that handle to check status
- The server doesn't reply untill it  has the response.

**Examples:**  
- Legacy real-time apps  
- Pre-WebSocket chat apps  

**Pros:**  
- Near real-time updates  
- Better than short polling  

**Cons:**  
- More overhead than true push  
- Ties up connections  

##  Comparison Table

| Pattern       | Connection Style       | Update Speed       | Server Load    | Network Efficiency |
|---------------|-----------------------|-------------------|----------------|-------------------|
| **Push**       | Persistent connection  | Real-time          | Medium-High     | High               |
| **Short Poll** | Many short-lived conn. | Delayed (interval) | High            | Low                |
| **Long Poll**  | Repeated long-held conn| Near real-time     | Medium          | Medium             |

## Summary

- **Push:** Ideal for real-time apps (chat, games, live dashboards).
- **Long Poll:** Fallback for real-time where push isn’t available.
- **Short Poll:** Simple, but inefficient — avoid if possible.
