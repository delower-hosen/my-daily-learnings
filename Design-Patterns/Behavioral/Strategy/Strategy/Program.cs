using Strategy;

var context = new PaymentContext();

context.SetPaymentStrategy(new CreditCardPayment());
context.ExecutePayment();

context.SetPaymentStrategy(new PayPalPayment());
context.ExecutePayment();