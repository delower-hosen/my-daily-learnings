namespace Factory_Method
{
    public class SmsNotification : INotification
    {
        public void Send(string message)
        {
            Console.WriteLine("Sending Sms: {0}", message);
        }
    }
}
