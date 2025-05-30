using Bridge_Pattern.Notifications;
using Bridge_Pattern.Senders;

IMessageSender emailSender = new EmailSender();
IMessageSender smsSender = new SmsSender();

Notification alertNotification = new AlertNotification(emailSender);
alertNotification.Send("Critical System Failure!");

Notification promoNotification = new PromotionNotification(smsSender);
promoNotification.Send("50% off on all items!");

// Extending easily with a new sender
IMessageSender pushSender = new PushNotificationSender();
Notification alertPush = new AlertNotification(pushSender);
alertPush.Send("Unauthorized login detected.");