# Delegate and Event in C#

## Delegates

A **delegate** is a reference type that holds references to methods with a specific signature. It allows methods to be treated as variables.

### Syntax
```csharp
public delegate void Greet(string name);
```

### Why Use Delegates?
- Pass methods as arguments
- Implement callbacks
- Define event handlers
- Enable multi-method invocation (multicast)

### Example
```csharp
public delegate void Greet(string name);

Greet greet = (name) => Console.WriteLine("Hello " + name);
greet += (name) => Console.WriteLine("Hi " + name);
greet("Alice");
// Output:
// Hello Alice
// Hi Alice
```

### Custom vs Built-in Delegates
- Custom: `delegate int Operation(int a, int b);`
- Built-in:
  - `Func<int, int, int>` (for return values)
  - `Action<string>` (no return)
  - `Predicate<string>` (returns bool)

```csharp
Func<int, int, int> add = (a, b) => a + b;
Console.WriteLine(add(2, 3)); // 5
```

## LINQ and Delegates
LINQ heavily relies on delegates, particularly the built-in ones like `Func<>`, `Action<>`, and `Predicate<>`. Most LINQ methods (like `Where`, `Select`, `Any`, `All`) accept lambda expressions that are compiled into delegate instances.

### Example
```csharp
List<int> numbers = new() { 1, 2, 3, 4, 5 };
var evens = numbers.Where(n => n % 2 == 0);

# Under the hood:
IEnumerable<int> evens = Enumerable.Where(numbers, n => n % 2 == 0);
```
Here, `n => n % 2 == 0` is compiled into a `Func<int, bool>` delegate, because `Where` expects `IEnumerable<T>.Where(Func<T, bool> predicate)`.

We can also write this explicitly:
```csharp
Func<int, bool> isEven = n => n % 2 == 0;
var evens = numbers.Where(isEven);
```

Thus, **delegates enable functional-style operations in LINQ**.

## Multicast Delegates
A delegate can point to multiple methods. When invoked, it calls all methods in order.

```csharp
Greet greet = (name) => Console.WriteLine("Hello " + name);
greet += (name) => Console.WriteLine("Hi " + name);
greet("Bob");
```

## Events

An **event** is a wrapper around a delegate that allows safe subscription but only allows the declaring class to invoke it.

### Declaration
```csharp
public delegate void OnNotify(string message);
public event OnNotify? NotifyEvent;
```

### Raising an Event
```csharp
NotifyEvent?.Invoke("Hello from event!");
```

### Why Use Events?
- Protect delegate invocation
- Allow multiple listeners
- Decouple publisher and subscribers

### Example
```csharp
public class NotificationService {
    public event OnNotify? NotifyEvent;

    public void NotifyAll(string message) {
        NotifyEvent?.Invoke(message);
    }
}

public class NotificationHandlers {
    public static void NotifyByEmail(string message) => Console.WriteLine("Email: " + message);
    public static void NotifyBySms(string message) => Console.WriteLine("SMS: " + message);
}

var service = new NotificationService();
service.NotifyEvent += NotificationHandlers.NotifyByEmail;
service.NotifyEvent += NotificationHandlers.NotifyBySms;

service.NotifyAll("System update complete.");
```

## Summary Table
| Feature       | Delegate                       | Event                                 |
|---------------|--------------------------------|----------------------------------------|
| Purpose       | Method reference               | Notification mechanism                |
| Can Invoke?   | Yes, from anywhere             | Only from inside declaring class      |
| Can Subscribe?| Yes                            | Yes                                   |
| Multicast?    | Yes                            | Yes                                   |

---

## Quick Recall
- **Delegate = method pointer**
- **Multicast = + operator on delegate**
- **Event = safe delegate with only raise rights in publisher**
- Use `?.Invoke()` to raise safely
- Prefer `Func<>`, `Action<>`, `Predicate<>` for common patterns
