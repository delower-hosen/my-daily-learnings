using Abstract_Factory;

IUIFactory factory;

string platform = "Windows";

if (platform == "Windows")
    factory = new WindowsUIFactory();
else
    factory = new MacUIFactory();

Client client = new Client(factory);
client.RenderUI();