using Factory_Method;
using Factory_Method.Factories;

NotificationFactory notificationFactory;

notificationFactory = new EmailNotificationFactory();
INotification emailNotification = notificationFactory.CreateNotification();
emailNotification.Send("Hello, you've got an email");

notificationFactory = new SmsNotificationFactory();
INotification smsNotification = notificationFactory.CreateNotification();
smsNotification.Send("This is an SMS notification.");

notificationFactory = new PushNotificationFactory();
INotification pushNotification = notificationFactory.CreateNotification();
pushNotification.Send("You have a new push alert");