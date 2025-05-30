namespace Bridge_Pattern.Senders
{
    public class EmailSender : IMessageSender
    {
        public void Send(string message) => Console.WriteLine($"Email sent: {message}");
    }
}
