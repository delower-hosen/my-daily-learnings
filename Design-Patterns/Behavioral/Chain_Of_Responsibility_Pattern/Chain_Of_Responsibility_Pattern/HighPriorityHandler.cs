namespace Chain_Of_Responsibility_Pattern
{
    public class HighPriorityHandler : TicketHandler
    {
        public override void HandleTicket(string priority, string ticket)
        {
            if (priority == "High")
            {
                Console.WriteLine("Ticket handled by Manager: " + ticket);
            }
            else
            {
                _nextHandler?.HandleTicket(priority, ticket);
            }
        }
    }
}
