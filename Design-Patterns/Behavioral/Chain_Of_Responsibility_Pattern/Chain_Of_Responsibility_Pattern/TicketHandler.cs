namespace Chain_Of_Responsibility_Pattern
{
    public abstract class TicketHandler
    {
        protected TicketHandler? _nextHandler;
        public TicketHandler SetNextHandler(TicketHandler nextHandler)
        {
            _nextHandler = nextHandler;
            return nextHandler;
        }

        public abstract void HandleTicket(string priority, string ticket);
    }
}
