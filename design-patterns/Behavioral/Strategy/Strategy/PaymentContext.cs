namespace Strategy
{
    public class PaymentContext
    {
        private IPaymentStrategy _paymentStrategy;

        public void SetPaymentStrategy(IPaymentStrategy strategy)
        {
            _paymentStrategy = strategy;
        }

        public void ExecutePayment()
        {
            _paymentStrategy.Pay();
        }
    }
}
