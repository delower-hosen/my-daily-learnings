# Singleton Pattern

## What is it?

The Singleton Pattern is a creational design pattern that ensures a class has only one instance and provides a global point of access to that instance. It restricts the instantiation of a class to a single object and provides a way to access it directly.

This pattern is useful when exactly one object is needed to coordinate actions across the system.

## 💡 Problem it Solves

Ensures a single instance: Prevents multiple instances of a class in situations where a single shared resource is needed (e.g., configuration, logging, cache, etc.).

Provides global access: Offers a central point to access the instance across the application.

Lazy initialization: The instance is only created when it is actually needed, which can save resources.

## When to Use

When you need to control access to shared resources.

When managing a global state (e.g., application configuration, logging).

When a single point of coordination is required.

## 🛠️ Key Components

### 1. **Private Constructor**
   - Prevents direct instantiation of the class from outside..

### 2. **Private Static Instance Variable**
   - Holds the single instance of the class.

### 3. **Public Static Method or Property**
   - Provides a global access point to the instance and ensures only one instance is created.