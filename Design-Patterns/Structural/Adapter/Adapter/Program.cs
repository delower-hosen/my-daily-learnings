using Adapter;

var newSystem = new NewSystem();

var oldSystem = new EmployeeDetailsAdapter(newSystem);

var employeeInfo = oldSystem.GetEmployeeDetails();

Console.WriteLine($"Employee Name: {employeeInfo.Name}");
Console.WriteLine($"Department: {employeeInfo.Department}");
Console.WriteLine($"Age: {employeeInfo.Age}");