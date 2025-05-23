using ClassLibrary1;

namespace EventAndDelegate
{
    public class Program
    {
        // Custom delegate to represent greeting methods
        public delegate void Greet(string name);

        // Custom delegate to represent operations on two integers returning an integer
        public delegate int TwoNumber(int a, int b);

        public static void Main()
        {
            Console.WriteLine("=== Multicast Delegate Demo ===");

            // Assign a lambda to the delegate
            Greet greet = (name) => Console.WriteLine("Hello " + name);

            // Add another anonymous method to the invocation list
            greet += (name) => Console.WriteLine("Hi " + name);

            // When invoking, all methods attached to the delegate run in order
            greet("Alice");
            // Output:
            // Hello Alice
            // Hi Alice

            Console.WriteLine("\n=== Custom Delegate vs Built-in Func Demo ===");

            // Using custom delegate
            TwoNumber twoNumberAdder = (a, b) => a + b;
            TwoNumber twoNumberMultiplier = (a, b) => a * b;

            Console.WriteLine("Custom delegate addition: " + twoNumberAdder(2, 3));       // 5
            Console.WriteLine("Custom delegate multiplication: " + twoNumberMultiplier(2, 3)); // 6

            // Using built-in generic delegate Func<>
            Func<int, int, int> twoNumberAdderFunc = (a, b) => a + b;
            Func<int, int, int> twoNumberMultiplierFunc = (a, b) => a * b;

            Console.WriteLine("Func<> addition: " + twoNumberAdderFunc(2, 3));        // 5
            Console.WriteLine("Func<> multiplication: " + twoNumberMultiplierFunc(2, 3));  // 6

            Console.WriteLine("\n=== Event & Delegate Demo ===");

            // Instantiate the service that exposes an event
            NotificationService notificationService = new();

            // Subscribe named methods to the event
            notificationService.NotifyEvent += NotificationHandlers.NotifyByEmail;
            notificationService.NotifyEvent += NotificationHandlers.NotifyBySms;
            notificationService.NotifyEvent += NotificationHandlers.NotifyByPush;

            // Subscribe an anonymous method to the event
            OnNotify anonymousHandler = (message) => Console.WriteLine($"Notification sent by anonymous handler: {message}");
            notificationService.NotifyEvent += anonymousHandler;

            // Trigger the event, all subscribers get notified
            notificationService.NotifyAll("Hello, event and delegates!");

            Console.WriteLine("\n=== Func Delegate Demo ===");

            Func<int, int, int> adder = (x, y) => x + y;

            // This prints the delegate type info, not the result
            Console.WriteLine("Printing delegate object: " + adder);

            // To print actual result, invoke the delegate with arguments:
            Console.WriteLine("Result of adder(10, 20): " + adder(10, 20));
        }
    }
}