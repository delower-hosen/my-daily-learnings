 # 🕹️ Command Pattern

## What is it?

The **Command Pattern** is a behavioral design pattern that turns a request into a standalone object that encapsulates:
- **What** action needs to be done
- **Which object** will do it
- And optionally, **when** and **how** it should be done

It decouples the **object that invokes the operation** (Invoker) from the one that knows **how to perform it** (Receiver).

> Think of it like a remote control that can be configured to control any device (light, stereo, garage door) without knowing how the device actually works.

---

## 💡 Problem it Solves

- You want to **parameterize objects with actions** (e.g., scheduling, queues, macro commands).
- You want to **decouple sender and receiver**, so either can change independently.
- You want to implement features like **undo/redo**, **logging**, or **transaction history**.

---

## 🕰️ When to Use

- You need to issue requests to objects without knowing anything about the operation or the receiver.
- You want to **queue, log, or undo** operations.
- You want to encapsulate user actions as objects (like menu items, buttons, or keyboard shortcuts).

---

## 🛠️ Key Components

### 1. Command (ICommand)
An interface with a method like `Execute()`. All command classes implement this.

### 2. Concrete Commands
Implement the `Command` interface and **bind a Receiver** to an action.

### 3. Receiver
Knows how to perform the action. The command delegates the call to this.

### 4. Invoker
Asks the command to carry out the request (e.g., a Remote Control, Button, UI element).

### 5. Client
Sets up the command objects and connects the invoker to the receiver.


