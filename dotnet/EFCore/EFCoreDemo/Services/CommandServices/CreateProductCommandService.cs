using Domain.Commands;
using Domain.Contracts;
using EfCore.PostgreSql.DomainModels.Entities;
using EfCore.PostgreSql.Repositories;

namespace Services.CommandServices
{
    public class CreateProductCommandService(IRepository<Product> productRepository) : ICreateProductCommandService
    {
        private readonly IRepository<Product> _productRepository = productRepository;

        public async Task CreateProductAsync(CreateProductCommand command)
        {
            var product = new Product
            {
                Name = command.Name,
                Description = command.Description,
                Price = command.Price,
                Quantity = command.Quantity
            };

            await _productRepository.AddAsync(product);
            await _productRepository.SaveChangesAsync();
        }
    }
}
