using Bridge_Pattern.Senders;

namespace Bridge_Pattern.Notifications
{
    public class PromotionNotification : Notification
    {
        public PromotionNotification(IMessageSender messageSender) : base(messageSender) { }

        public override void Send(string message)
        {
            Console.Write("Promotion: ");
            _messageSender.Send(message);
        }
    }
}
