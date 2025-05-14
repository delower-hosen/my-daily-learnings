namespace Factory_Method
{
    public class PushNotification : INotification
    {
        public void Send(string message)
        {
            Console.WriteLine("Sending Push Notification: {0}", message);
        }
    }
}
