namespace Chain_Of_Responsibility_Pattern
{
    public class LowPriorityHandler : TicketHandler
    {
        public override void HandleTicket(string priority, string ticket)
        {
            if (priority == "Low")
            {
                Console.WriteLine("Ticket handled by General Support: " + ticket);
            }
            else
            {
                _nextHandler?.HandleTicket(priority, ticket);
            }
        }
    }
}
