namespace Chain_Of_Responsibility_Pattern
{
    public class MediumPriorityHandler : TicketHandler
    {
        public override void HandleTicket(string priority, string ticket)
        {
            if (priority == "Medium")
            {
                Console.WriteLine("Ticket handled by Senior Support: " + ticket);
            }
            else
            {
                _nextHandler?.HandleTicket(priority, ticket);
            }
        }
    }
}
