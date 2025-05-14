namespace Factory_Method
{
    public class EmailNotification : INotification
    {
        public void Send(string message)
        {
            Console.WriteLine("Sending Email: {0}", message);
        }
    }
}
