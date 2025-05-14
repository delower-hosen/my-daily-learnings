# 👁️ Observer Pattern

## What is it?

The Observer Pattern is a **behavioral design pattern** where an object (called the **Subject**) maintains a list of dependents (called **Observers**) and notifies them automatically of any state changes, usually by calling one of their methods.

It’s like a **subscription system** — observers subscribe to a subject, and they get updates whenever the subject changes.

---

## 💡 Problem it Solves

- One-to-many dependency between objects where one change needs to update multiple others.
- Need to **decouple** the subject (the data owner) from the observers (the data users).
- Want to **broadcast events** to multiple listeners in a scalable and reusable way.

---

## 🧩 When to Use

- When changes in one object should automatically trigger updates in other objects.
- When you need a **publisher/subscriber** mechanism.
- When you're building systems with **live data updates** like dashboards, weather stations, stock tickers, etc.

---

## 🛠️ Key Components

### 1. Subject Interface

Defines methods for attaching, detaching, and notifying observers.

### 2. Observer Interface
Defines the Update method that observers must implement.

### 3. Concrete Subject
Holds the actual data and notifies all registered observers when the data changes.

### 4. Concrete Observers
React to data changes from the subject
