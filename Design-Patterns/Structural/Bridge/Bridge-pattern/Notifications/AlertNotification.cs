using Bridge_Pattern.Senders;

namespace Bridge_Pattern.Notifications
{
    public class AlertNotification : Notification
    {
        public AlertNotification(IMessageSender messageSender) : base(messageSender) { }

        public override void Send(string message)
        {
            Console.Write("Alert: ");
            _messageSender.Send(message);
        }
    }
}
