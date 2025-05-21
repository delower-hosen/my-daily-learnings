
# C# Generics

## What Are Generics?
Generics allow you to define type-safe data structures and methods without committing to actual data types until the class or method is instantiated.

### Example:
```csharp
public class Box<T>
{
    public T Value { get; set; }
}
```

## Why Use Generics?
- **Type Safety**: Avoid boxing/unboxing and runtime casting.
- **Reusability**: Write once, use for any type.
- **Performance**: Eliminate unnecessary casting and boxing.

## Generic Methods
Generic methods allow you to define a method with type parameters, making the method reusable for different types without duplicating code

```csharp
public T Max<T>(T a, T b) where T : IComparable<T>
{
    return a.CompareTo(b) > 0 ? a : b;
}

int biggerInt = Max(5, 10); // returns 10
string longerString = Max("cat", "elephant"); // returns "elephant" (lexical comparison)
DateTime laterDate = Max(DateTime.Now, DateTime.UtcNow); // returns the later date/time
```
The types int, string, and DateTime all implement IComparable<T>, which is why they work with the Max method.

## Generic Constraints
- `where T : struct` – Value types only
- `where T : class` – Reference types only
- `where T : new()` – Must have a public parameterless constructor
- `where T : BaseClass` – Must inherit from `BaseClass`
- `where T : interfaceName` – Must implement the interface

### Example:
```csharp
public class Repository<T> where T : IEntity, new()
{
    public T CreateInstance() => new T();
}
```

## Advanced Generics

### Generic Interfaces and Inheritance
```csharp
public interface IRepository<T> { }
public class UserRepository : IRepository<User> { }
```

### Generic Delegates
```csharp
public delegate T Transformer<T>(T input);
```

### Generic Constraints Combination
```csharp
where T : BaseClass, IInterface, new()
```

### Open & Closed Generics
```csharp
public interface IRepository<T>
{
    void Add(T item);
    T GetById(int id);
}

public class Repository<T> : IRepository<T>
{
    public void Add(T item) => Console.WriteLine($"Added {item}");
    public T GetById(int id) => default!;
}

public class UserService
{
    private readonly IRepository<User> _userRepo;

    public UserService(IRepository<User> userRepo)
    {
        _userRepo = userRepo;
    }

    public void SaveUser(User user) => _userRepo.Add(user);
}

services.AddSingleton(typeof(IRepository<>), typeof(Repository<>));
```
## Best Practices
- Use constraints wisely for safety.
- Don’t overuse generics—use only when type flexibility is needed.
- Prefer meaningful type parameter names like `TEntity`, `TResult`, `TInput`.
