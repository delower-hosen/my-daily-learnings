namespace Adapter
{
    public class NewSystem : INewSystem
    {
        public EmployeeDetails GetEmployeeDetails()
        {
            return new EmployeeDetails
            {
                EmployeeName = "John",
                EmployeeDepartment = "Finance",
                EmployeeAge = 31
            };
        }
    }
}
