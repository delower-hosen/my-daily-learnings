# Request-Response (Synchronous)

The most common and simple communication pattern:

## Flow
1 **Client sends a Request**
- Request has a clear boundary (start and end)  
- Packaged using an agreed **protocol** (e.g., HTTP, gRPC)  
- Contains data in an agreed **message format** (e.g., JSON, XML, Protobuf)

2 **Server parses the Request**
- Parses HTTP method, headers, path 
- Validates structure (e.g., JSON, XML, Protobuf)  
- Authenticates/authorizes if required

3️ **Server processes the Request**  
- Runs business logic  
- Fetches data, performs computation  

4 **Server sends a Response**  
- Packaged in agreed format (e.g., JSON, XML, Protobuf)  

5 **Client parses and consumes the Response**  
- Displays, stores, or triggers further actions  

| Client           | Kestrel / MVC                  | Your Controller |
| ---------------- | ------------------------------ | --------------- |
| POST JSON Body → |                                |                 |
|                  | Parse HTTP + headers           |                 |
|                  | Deserialize JSON → C# object   |                 |
|                  | Call `GetCenterRealizations()` |                 |
|                  |                                | Your logic runs |
|                  | ← Serialize response JSON      |                 |
|                  | ← Send HTTP response           |                 |


## Where it is used?
- Web browsing (HTTP, HTTPS)
- Remote procedure calls (gRPC, SOAP)
- Database protocols (SQL, NoSQL query APIs)
- API integrations (REST, GraphQL)

## Where Request-Response Falls Short

- **Notification services**  
  (Polling is inefficient: client keeps asking “Any new notifications?”)
  
- **Chat applications**  
  (Needs low-latency bidirectional updates)

- **Long-running operations**  
  (E.g., report generation; client may disconnect)

- **Unreliable networks**  
  (Risk of partial uploads, broken connections)

## Demo: Inspecting a Real Request with `curl`
Run:
```bash
curl -v --trace out.txt http://www.google.com
```