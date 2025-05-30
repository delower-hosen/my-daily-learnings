# Chain of Responsibility Pattern

## What is it?

The Chain of Responsibility is a **behavioral design pattern** that allows passing a request along a chain of handlers. Each handler can either process the request or forward it to the next handler in the chain. 

This pattern provides a way to decouple request senders from receivers, making the system more flexible.

## 💡 Problem it Solves

- **Avoids tight coupling** between sender and receiver. In other words, the sender doesn't need to know who will handle the request.
- **Dynamically configures the chain at runtime**, allowing flexibility in handling requests based on the order and types of handlers.
- **Simplifies complex conditional logic** by eliminating the need for `if/else` chains or `switch` statements.

## When to Use

- When **multiple handlers** can process a request, and you don’t know in advance which handler should process the request.
- When you need **dynamic, runtime-configurable processing chains** (e.g., you want to add, remove, or reorder handlers at runtime).
- When you want to follow the **Open/Closed Principle**: adding new handlers without modifying the existing code that sends requests.

## 🛠️ Key Components

### 1. **Handler (Abstract Class)**
   - Declares the method to handle requests and to set the next handler in the chain.
   - Provides an interface to forward requests to the next handler if necessary.

### 2. **Concrete Handlers**
   - Implement the request handling logic and decide whether to pass the request forward in the chain or handle it themselves.
   - Each concrete handler handles a specific part of the request.

### 3. **Client**
   - Configures the chain by setting up the concrete handlers and linking them together.
   - Initiates the request by passing it to the first handler in the chain.
