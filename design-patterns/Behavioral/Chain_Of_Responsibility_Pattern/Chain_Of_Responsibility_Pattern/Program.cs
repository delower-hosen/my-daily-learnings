using Chain_Of_Responsibility_Pattern;

// create handlers
var lowPriorityHandler = new LowPriorityHandler();
var mediumPriorityHandler = new MediumPriorityHandler();
var highPriorityHandler = new HighPriorityHandler();

// set up the chain
//lowPriorityHandler.SetNextHandler(mediumPriorityHandler);
//mediumPriorityHandler.SetNextHandler(highPriorityHandler);

lowPriorityHandler
    .SetNextHandler(mediumPriorityHandler)
    .SetNextHandler(highPriorityHandler);


// pass the tickets to the first handler
lowPriorityHandler.HandleTicket("Low", "Ticket 1");
lowPriorityHandler.HandleTicket("Medium", "Tickt 2");
lowPriorityHandler.HandleTicket("High", "Ticket 3");