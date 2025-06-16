# Backend Communication Design Patterns

Backend communication design patterns define how different components (e.g., services, APIs, databases) interact in a distributed system. The choice of pattern significantly affects **scalability**, **maintainability**, **performance**, and **resilience**.

## Categories of Communication

| Type            | Characteristics                     | Example Protocols       |
|-----------------|--------------------------------------|------------------------|
| **Synchronous**  | Client waits for an immediate reply  | REST, gRPC, SOAP, SQL   |
| **Asynchronous** | Client sends and continues work      | RabbitMQ, Kafka, MQTT   |