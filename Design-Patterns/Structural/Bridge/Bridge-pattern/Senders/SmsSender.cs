namespace Bridge_Pattern.Senders
{
    public class SmsSender : IMessageSender
    {
        public void Send(string message) => Console.WriteLine($"SMS sent: {message}");
    }
}
