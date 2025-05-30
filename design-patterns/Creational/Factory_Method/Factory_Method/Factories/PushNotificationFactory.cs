namespace Factory_Method.Factories
{
    public class PushNotificationFactory : NotificationFactory
    {
        public override INotification CreateNotification()
        {
            return new PushNotification();
        }
    }
}
