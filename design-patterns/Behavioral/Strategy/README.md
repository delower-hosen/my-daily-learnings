# 🧠 Strategy Pattern

## What is it?

The **Strategy Pattern** is a behavioral design pattern that enables selecting an algorithm’s behavior at runtime. It defines a family of algorithms, encapsulates each one, and makes them interchangeable without altering the client code that uses them.

It helps promote the **Open/Closed Principle** by allowing algorithms to be selected and changed dynamically.

---

## 💡 Problem it Solves

- Avoids long **if-else or switch-case statements** for algorithm selection.
- Allows for **easy addition of new strategies** without modifying existing code.
- Provides a clean way to **encapsulate and decouple algorithms**.

---

## When to Use

- When you have different variants of an algorithm (e.g., different payment types).
- When you want to switch behavior at runtime.
- When behavior varies by context or user choice.

---

## 🛠️ Key Components

### 1. **Strategy Interface**
   - Declares a common method for all supported algorithms.

### 2. **Concrete Strategies**
   - Implement different variants of the algorithm.

### 3. **Context**
   - Uses a strategy object and delegates it to execute the behavior.