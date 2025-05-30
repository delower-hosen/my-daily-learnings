 
# Builder Pattern

## What is it?

The Builder is a **creational design pattern** that allows the construction of complex objects step by step. It separates the construction process of an object from its representation, enabling the same construction process to create different types of objects.

Instead of having a constructor with a long parameter list, the Builder pattern uses a step-by-step approach to build objects, which makes the code cleaner, more readable, and easier to maintain.

## 💡 Problem it Solves

- **Avoids constructor telescoping**: When an object has multiple optional fields, constructors can become cumbersome with many parameters. The Builder pattern avoids this by offering a cleaner, more flexible way to construct objects.
- **Improves readability**: The step-by-step construction allows users to clearly see the configuration of the object, without passing all parameters at once.
- **Supports immutability**: Builder pattern can be used to construct immutable objects by setting properties incrementally and then returning the final object.

## When to Use

- When you need to construct an object with many possible configurations or optional parameters.
- When an object needs to be constructed in a sequence of steps (e.g., many attributes need to be configured).
- When you want to separate the construction logic from the object itself.
- When you need to avoid the complexity of having multiple constructors in a class, especially when there are many optional parameters.

## 🛠️ Key Components

### 1. **Product**
   - Represents the complex object that is being built. It typically contains many fields that are set during the construction process.

### 2. **Builder**
   - Declares the construction process and provides methods for setting the various parts of the product.
   - Returns the constructed object once the construction is complete.

### 3. **Concrete Builder**
   - Implements the builder interface and provides the specific construction logic for the product.
   - Constructs and assembles the parts of the product.

### 4. **Director (Optional)**
   - In some cases, a Director class controls the construction process and ensures the product is built in a specific order.

### 5. **Client**
   - Initiates the construction process by using the builder. It calls the builder methods to set the desired attributes and finally calls the `Build()` method to get the constructed object.
