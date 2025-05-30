namespace Bridge_Pattern.Senders
{
    public class PushNotificationSender : IMessageSender
    {
        public void Send(string message) => Console.WriteLine($"Push Notification sent: {message}");
    }
}
