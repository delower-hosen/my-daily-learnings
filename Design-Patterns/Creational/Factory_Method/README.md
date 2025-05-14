# Factory Method Pattern

## What is it?

The Factory Method is a **creational design pattern** that provides an interface for creating objects but allows subclasses to alter the type of objects that will be created.

Instead of calling a constructor directly, the pattern delegates the instantiation process to factory methods, promoting loose coupling and scalability.

## 💡 Problem it Solves

- **Removes direct dependency on concrete classes**, making the code easier to maintain and extend.
- **Encapsulates object creation logic**, avoiding repeated instantiation logic across the codebase.
- **Improves testability** by allowing the use of mock objects for different implementations.

## When to Use

- When the **exact type of object to create is determined at runtime**.
- When a **class should not depend on concrete implementations** but rather an abstraction.
- When you want to **follow the Open/Closed Principle**: allowing new types of products without modifying existing code.

## 🛠️ Key Components

### 1. **Product (Interface or Abstract Class)**
   - Declares the common behavior for all products.

### 2. **Concrete Products**
   - Implement the product interface.

### 3. **Creator (Abstract Factory Class)**
   - Declares the factory method that returns an object of the product type.
   - Can provide a default implementation of the factory method.

### 4. **Concrete Factories**
   - Override the factory method to instantiate specific product implementations.

### 5. **Client**
   - Calls the factory method instead of creating objects directly.