using Prototype;

var reportTemplate = new DocumentTemplate("Report", "Annual Report", new List<string> { "Yearly" });

Console.WriteLine("Original Report Template:");
Console.WriteLine(reportTemplate);
Console.WriteLine();

// Perform Shallow Clone
var shallowClone = reportTemplate.Clone();
shallowClone.Title = "Invoice (Shallow)";
shallowClone.ContentBody = "Shallow cloned invoice report";
shallowClone.Tags.Add("Monthly"); // Modifies the shared list

Console.WriteLine("Shallow Cloned Invoice Template:");
Console.WriteLine(shallowClone);
Console.WriteLine("Original Report Template After Shallow Clone:");
Console.WriteLine(reportTemplate); // Notice how the "Yearly" tag is also modified!
Console.WriteLine();

// Perform Deep Clone
var deepClone = reportTemplate.DeepClone();
deepClone.Title = "Invoice (Deep)";
deepClone.ContentBody = "Deep cloned invoice report";
deepClone.Tags.Add("Quarterly"); // Modifies only the deep clone

Console.WriteLine("Deep Cloned Invoice Template:");
Console.WriteLine(deepClone);
Console.WriteLine("Original Report Template After Deep Clone:");
Console.WriteLine(reportTemplate); // Original remains unchanged
