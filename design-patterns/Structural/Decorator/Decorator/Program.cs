using Decorator;

IText myText = new PlainText("Hello, World!");
myText = new BoldText(myText);         // <b>Hello, World!</b>
myText = new ItalicText(myText);       // <i><b>Hello, World!</b></i>
myText = new UnderlineText(myText);    // <u><i><b>Hello, World!</b></i></u>

Console.WriteLine(myText.GetContent());