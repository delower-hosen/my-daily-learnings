using Domain.Commands;
using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace WebService.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class ProductCommandController : ApiControllerBase
    {
        private readonly ILogger<ProductCommandController> _logger;
        private readonly IMediator _mediator;

        public ProductCommandController(ILogger<ProductCommandController> logger,
            IMediator mediator)
        {
            _logger = logger;
            _mediator = mediator;
        }

        [HttpPost]
        public async Task<IActionResult> Post([FromBody] CreateProductCommand command)
        {
            await _mediator.Send(command);
            return Ok("Created task successfully!");
        }
    }
}
