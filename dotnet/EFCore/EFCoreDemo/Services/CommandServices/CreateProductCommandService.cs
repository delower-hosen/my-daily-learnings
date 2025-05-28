using Domain.Commands;
using Domain.Contracts;

namespace Services.CommandServices
{
    public class CreateProductCommandService : ICreateProductCommandService
    {
        public Task CreateProductAsync(CreateProductCommand command)
        {
            throw new NotImplementedException();
        }
    }
}
