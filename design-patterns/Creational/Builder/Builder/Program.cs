using Builder;

//var gamingPC = new Computer.Builder()
//    .SetCPU("Intel i9")
//    .SetRAM("32GB")
//    .SetStorage("1TB SSD")
//    .AddGraphicsCard()
//    .AddWiFi()
//    .Build();

var gamingPC = new Computer.Builder();

gamingPC.SetCPU("Intel i9");
gamingPC.SetRAM("32GB");
gamingPC.SetStorage("1TB SSD");
gamingPC.AddGraphicsCard();
gamingPC.AddWiFi();
gamingPC.Build();

Console.WriteLine(gamingPC);