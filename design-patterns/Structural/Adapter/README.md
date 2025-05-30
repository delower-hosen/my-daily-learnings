# Adapter Pattern

## What is it?

The Adapter Pattern is a structural design pattern that allows two incompatible interfaces to work together. It acts as a bridge between a class with an existing interface and a client that expects a different interface.

It’s like a plug adapter — it lets devices with incompatible plugs connect to a different power outlet.

## 💡 Problem it Solves
	- Incompatible Interfaces: You want to use an existing class, but its interface doesn't match your expectations.

	- No Modifications Allowed: You cannot change the source code of the class you're trying to reuse (e.g., third-party or legacy systems).

	- Integration without Breaking: You need to integrate a class into your app without changing the existing client code.

## When to Use
When you want to reuse an existing class whose interface doesn't match the one you need.

When you're working with legacy code or third-party libraries.

When you want to standardize access to multiple incompatible classes.

## 🛠️ Key Components
### 1. Target Interface
	The interface your client expects.

## 2. Adaptee
	The class you want to use but has an incompatible interface.

## 3. Adapter
	A class that implements the Target interface and internally uses the Adaptee to fulfill requests.

