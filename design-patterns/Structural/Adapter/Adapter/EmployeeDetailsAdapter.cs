using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Adapter
{
    public class EmployeeDetailsAdapter : IOldSystem
    {
        private readonly INewSystem _newSystem;

        public EmployeeDetailsAdapter(INewSystem newSystem)
        {
            _newSystem = newSystem;
        }
        public EmployeeInfo GetEmployeeDetails()
        {
            var employeeDetails = _newSystem.GetEmployeeDetails();

            return new EmployeeInfo
            {
                Name = employeeDetails.EmployeeName,
                Department = employeeDetails.EmployeeDepartment,
                Age = employeeDetails.EmployeeAge
            };
        }
    }
}
