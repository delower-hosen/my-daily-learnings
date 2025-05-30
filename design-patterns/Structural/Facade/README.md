 # Facade Pattern

## What is it?

The **Facade Pattern** is a structural design pattern that provides a simplified interface to a larger body of complex subsystems. It hides the complexities of the system and provides a cleaner, more readable way to interact with it.

---

## 💡 Problem it Solves

- Large systems can become difficult to work with directly due to many interconnected classes and APIs.
- The Facade pattern provides a unified interface to a set of interfaces, making the subsystem easier to use.
- It reduces coupling between clients and subsystems.

---

## 📦 Real-World Analogy

When you visit a **bank**, you don’t interact with every department directly — you go to a **front desk** (facade), and they handle the internal processes (documents, verifications, accounts).

---

## ✅ When to Use

- When you want to provide a simple interface to a complex subsystem.
- When you want to reduce dependencies between the client code and complex subsystems.
- When you want to layer your system with abstraction.

---

## 🧩 Components

### 1. **Facade Class**
- Provides simplified methods to the client.
- Delegates calls to underlying systems.

### 2. **Subsystem Classes**
- Handle the actual work behind the scenes.
- Are hidden from direct client access.