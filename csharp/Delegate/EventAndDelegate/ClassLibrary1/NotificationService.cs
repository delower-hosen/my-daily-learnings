namespace ClassLibrary1
{
    public delegate void OnNotify(string message);
    public class NotificationService
    {
        public event OnNotify? NotifyEvent;
        public void NotifyAll(string message)
        {
            NotifyEvent?.Invoke(message);
        }
    }
}
