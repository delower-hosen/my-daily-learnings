using Domain.Commands;
using Domain.Contracts;
using MediatR;

namespace Domain.CommandHandlers
{
    public class CreateProductCommandHandler(ICreateProductCommandService createProductCommandService) : IRequestHandler<CreateProductCommand, bool>
    {
        private readonly ICreateProductCommandService _createProductCommandService = createProductCommandService;

        public async Task<bool> Handle(CreateProductCommand command, CancellationToken cancellationToken)
        {
            await _createProductCommandService.CreateProductAsync(command);
            return true;
        }
    }
}
