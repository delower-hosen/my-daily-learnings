namespace Singleton
{
    public class SingletonService
    {
        private static SingletonService? _instance;
        public static readonly object _lock = new();
        private SingletonService()
        {
            Console.WriteLine("Singleton instance created.");
        }

        public static SingletonService Instance
        {
            get
            {
                lock (_lock)
                {
                    return _instance ??= new SingletonService();
                }
            }
        }

        public void ShowMessage()
        {
            Console.WriteLine("Hello from Singleton!");
        }
    }
}
