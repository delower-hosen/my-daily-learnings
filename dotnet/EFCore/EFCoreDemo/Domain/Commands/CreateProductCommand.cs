using MediatR;

namespace Domain.Commands
{
    public class CreateProductCommand : IRequest<bool>
    {
        public string Name { get; set; } = default!;
        public decimal Price { get; set; }
    }
}
