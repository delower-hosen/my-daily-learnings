using Domain.Commands;

namespace Domain.Contracts
{
    public interface ICreateProductCommandService
    {
        Task CreateProductAsync(CreateProductCommand command);
    }
}
