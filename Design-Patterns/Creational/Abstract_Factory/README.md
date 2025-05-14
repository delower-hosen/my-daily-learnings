# Abstract Factory Pattern

## What is it?

The Abstract Factory is a **creational design pattern** that provides an interface for creating families of related or dependent objects without specifying their concrete classes.

It allows the creation of objects that follow a common theme but might vary across different families, ensuring that the client interacts only with the abstract interfaces, avoiding the need to know about specific object creation details.

## 💡 Problem it Solves

- **Ensures consistency** across related objects by defining common interfaces.
- **Decouples the client from the concrete class implementations**, making the system easier to extend and maintain.
- **Improves scalability** by allowing new families of products to be introduced without affecting existing code.
- **Promotes flexibility** by enabling the system to switch between different families of related objects.

## When to Use

- When you need to **create families of related or dependent objects** without specifying their concrete classes.
- When the client needs to interact with a family of related objects, but the exact object is chosen at runtime.
- When you want to avoid tight coupling between the client and the concrete implementations of the products.
- When you want to support **platform or theme independence**, like creating different UI components for Windows and macOS.

## 🛠️ Key Components

### 1. **Abstract Product (Interface or Abstract Class)**
   - Declares the common behavior for a family of related products (e.g., `IButton`, `ITextBox`).

### 2. **Concrete Products**
   - Implement the abstract product interfaces for different families (e.g., `WindowsButton`, `MacButton`).

### 3. **Abstract Factory**
   - Declares the methods for creating abstract products (e.g., `CreateButton`, `CreateTextBox`).
   - Typically provides an interface for creating families of products, but without specifying their concrete classes.

### 4. **Concrete Factories**
   - Implement the abstract factory methods to create concrete products specific to a family (e.g., `WindowsUIFactory`, `MacUIFactory`).

### 5. **Client**
   - Uses the abstract factory interface to create products, but does not depend on the concrete implementations of the objects.
   - Interacts only with the abstract product interfaces, ensuring that the client code remains independent of specific product families.
