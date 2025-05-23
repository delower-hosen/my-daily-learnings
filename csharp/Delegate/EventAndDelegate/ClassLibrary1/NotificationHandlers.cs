namespace ClassLibrary1
{
    public class NotificationHandlers
    {
        public static void NotifyByEmail(string message)
        {
            Console.WriteLine($"Notification sent by email: {message}");
        }

        public static void NotifyBySms(string message)
        {
            Console.WriteLine($"Notification sent by sms: {message}");
        }

        public static void NotifyByPush(string message)
        {
            Console.WriteLine($"Notification sent by push: {message}");
        }
    }
}
