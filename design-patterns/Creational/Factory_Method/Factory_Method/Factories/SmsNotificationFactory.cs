namespace Factory_Method.Factories
{
    public class SmsNotificationFactory : NotificationFactory
    {
        public override INotification CreateNotification()
        {
            return new SmsNotification();
        }
    }
}
