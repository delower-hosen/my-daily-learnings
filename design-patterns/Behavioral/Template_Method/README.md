 # 🧠 Template Pattern

## What is it?

The **Template Pattern** is a behavioral design pattern that defines the **skeleton of an algorithm** in a base class but allows **subclasses to override specific steps** of that algorithm without changing its overall structure.

It promotes **code reuse** and ensures **algorithm consistency**, while allowing flexibility in parts of the process.

---

## 💡 Problem it Solves

- Eliminates **code duplication** when different classes share similar workflow logic.
- Keeps **core logic centralized** while allowing variation in steps.
- Provides a clean way to **enforce algorithm structure** with customizable behavior.

---

## When to Use

- When multiple classes follow the same sequence of operations with minor differences in some steps.
- When you want to **enforce a common structure** across related operations.
- When logic needs to be reused while still allowing some **customizable steps**.

---

## 🛠️ Key Components

### 1. **Abstract Class (Template)**
   - Defines the **template method** (the algorithm skeleton).
   - Provides default implementations of common steps.
   - Declares **abstract methods** (hooks) for steps to be implemented by subclasses.

### 2. **Concrete Subclasses**
   - Override the abstract methods to provide specific behaviors for those steps.
   - Inherit the core logic from the base class.

### 3. **Template Method**
   - A non-overridable method that defines the fixed sequence of operations, calling both fixed and customizable steps.
