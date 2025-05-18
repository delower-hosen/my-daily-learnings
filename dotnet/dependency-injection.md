# Dependency Injection in .NET Core

Dependency Injection (DI) is a **design pattern** used to achieve **Inversion of Control (IoC)** between classes and their dependencies, promoting loose coupling and maintainability.

## Core Concepts

### What is an IoC Container?

An **IoC Container** (Inversion of Control Container) is a framework or component responsible for **automatically creating, configuring, and injecting** dependencies into your classes.

Without IoC Container:
```csharp
var service = new MyService(new Repository());
```

With IoC Container, control is inverted — the container decides how and when to create `MyService` and inject the required `Repository`.

### Responsibilities of an IoC Container

- **Object creation:** Automatically instantiate classes and their dependencies.
- **Dependency injection:** Inject dependencies via constructors, methods, or properties.
- **Lifetime management:** Manage service lifetimes — singleton, transient, or scoped.
- **Abstraction resolution:** Resolve interfaces or abstract types to their concrete implementations.

### Built-in vs. Third-Party Containers

| Type                | Description                                 | Examples                               |
|---------------------|---------------------------------------------|--------------------------------------|
| **Built-in**        | Included with .NET Core; basic but efficient | `Microsoft.Extensions.DependencyInjection` |
| **Third-party**     | Provide advanced features & flexibility      | Autofac, Ninject, StructureMap, Unity |

### Key Concepts at a Glance

| Concept                  | Explanation                                    |
|--------------------------|------------------------------------------------|
| **IoC (Inversion of Control)** | Code does **not** create its own dependencies manually. |
| **IoC Container**         | Manages dependencies and their lifetimes automatically. |
| **Dependency Injection (DI)** | A pattern enabled by the IoC container to provide dependencies externally. |

## Why Use Dependency Injection?

- **Loose Coupling:** Components depend on **abstractions** (interfaces) instead of concrete implementations.
- **Testability:** Easier to inject mocks and stubs for unit testing.
- **Maintainability:** Easily swap or update implementations without modifying dependent code.
- **Scalability:** Supports modular, extensible architecture designs.

## Injection Types

### 1. Constructor Injection ✅ (Most Common & Recommended)

Dependencies are provided via the class constructor, ensuring dependencies are available when the object is created.

```csharp
public class MyService
{
    private readonly ILogger _logger;

    public MyService(ILogger logger)
    {
        _logger = logger;
    }
}
```

### 2. Method Injection

Dependencies are passed as method parameters, typically for optional or rarely used dependencies.

```csharp
public void LogInfo(ILogger logger)
{
    logger.Log("Injected via method");
}
```

## Service Lifetimes

### Transient

- Creates a **new instance** every time the service is requested.
- Use for lightweight, stateless services.

```csharp
services.AddTransient<IMyService, MyService>();
```

### Scoped

- Creates **one instance per request** (e.g., per HTTP request in a web app).
- Ideal for services that maintain state during a single user request, such as Entity Framework `DbContext`.

```csharp
services.AddScoped<IMyService, MyService>();
```

### Singleton

- Creates **one instance for the entire application lifetime**.
- Use for services that maintain shared state or are expensive to create.

```csharp
services.AddSingleton<IMyService, MyService>();
```

## Scope Hierarchy

### Service Scope

- Created **once per request**.
- Shared across components handling that request.

### Child Scope

- Created manually or used in background tasks.
- Allows creating a **new scope** to resolve scoped services independently.

```csharp
using (var scope = serviceProvider.CreateScope())
{
    var scopedService = scope.ServiceProvider.GetRequiredService<IMyService>();
    // Use scopedService here
}
```

## Service Locator Pattern (Anti-pattern)

Manually resolving dependencies from the container hides the actual dependencies a class needs, making code harder to maintain and test.

```csharp
var myService = serviceProvider.GetService<IMyService>();
```

**Avoid** using this pattern. Prefer explicit constructor injection.

## Best Practices

- **Prefer constructor injection** to make dependencies explicit.
- Register concrete implementations against interfaces to promote abstraction.
- Avoid calling `IServiceProvider` or service locators directly within your classes.
- Carefully choose lifetimes; for example, use `Scoped` for database contexts.
- Keep constructors concise to maintain readability and testability.
