 
# Prototype Pattern

## What is it?

The Prototype Pattern is a **creational design pattern** that allows copying existing objects without making the code dependent on their concrete classes. Instead of creating objects from scratch, the pattern enables cloning of objects to produce new instances with the same properties.

This pattern is particularly useful when object creation is costly or complex, and an efficient way to duplicate objects is needed.

## 💡 Problem it Solves

- **Avoids expensive object creation**: When creating an object is costly (e.g., requires database queries, complex calculations, or setup), cloning an existing object is much faster.
- **Reduces dependency on specific classes**: The Prototype pattern abstracts object creation, reducing tight coupling with concrete classes.
- **Enables runtime object configuration**: New objects can be created dynamically with customized properties based on existing ones.

## When to Use

- When creating new objects is expensive, and copying existing objects is more efficient.
- When objects should be independent of their concrete classes and created at runtime.
- When an object’s structure is complex and should be duplicated easily.

## 🛠️ Key Components

### 1. **Prototype (Interface or Abstract Class)**
   - Defines a method for cloning itself.

### 2. **Concrete Prototype**
   - Implements the cloning functionality.
   - Can perform either **shallow copy** (copying only value types and references) or **deep copy** (creating new instances of referenced objects).

### 3. **Client**
   - Uses the prototype instance to clone new objects instead of directly instantiating them.