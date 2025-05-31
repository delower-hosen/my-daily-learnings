using MediatR;

namespace Domain.Commands
{
    public class CreateProductCommand : IRequest<bool>
    {
        public string Name { get; set; } = default!;
        public string Description { get; set; } = default!;
        public double Price { get; set; }
        public int Quantity { get; set; }
    }
}
