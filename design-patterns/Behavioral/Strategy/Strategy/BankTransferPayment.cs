namespace Strategy
{
    public class BankTransferPayment : IPaymentStrategy
    {
        public void Pay()
        {
            Console.WriteLine("Paid using bank transfer");
        }
    }
}
