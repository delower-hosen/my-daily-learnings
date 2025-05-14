using Bridge_Pattern.Senders;

namespace Bridge_Pattern.Notifications
{
    public abstract class Notification
    {
        protected IMessageSender _messageSender;

        public Notification(IMessageSender messageSender)
        {
            _messageSender = messageSender;
        }

        public abstract void Send(string message);
    }
}
