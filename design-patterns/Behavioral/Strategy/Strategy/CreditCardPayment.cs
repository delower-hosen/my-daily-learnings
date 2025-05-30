namespace Strategy
{
    public class CreditCardPayment : IPaymentStrategy
    {
        public void Pay()
        {
            Console.WriteLine("Paid using credit card");
        }
    }
}
