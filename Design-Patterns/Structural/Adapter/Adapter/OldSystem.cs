namespace Adapter
{
    public class OldSystem : IOldSystem
    {
        public EmployeeInfo GetEmployeeDetails()
        {
            return new EmployeeInfo
            {
                Name = "John",
                Department = "Finance",
                Age = 31
            };
        }
    }
}
