namespace Strategy
{
    public class PayPalPayment : IPaymentStrategy
    {
        public void Pay()
        {
            Console.WriteLine("Paid using PayPal");
        }
    }
}
