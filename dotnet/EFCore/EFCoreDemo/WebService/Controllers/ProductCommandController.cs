using Domain.Commands;
using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace WebService.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class ProductCommandController(ILogger<ProductCommandController> logger,
        IMediator mediator) : ApiControllerBase
    {
        private readonly ILogger<ProductCommandController> _logger = logger;
        private readonly IMediator _mediator = mediator;

        [HttpPost]
        public async Task<IActionResult> Post([FromBody] CreateProductCommand command)
        {
            await _mediator.Send(command);
            return Ok("Created product successfully!");
        }
    }
}
