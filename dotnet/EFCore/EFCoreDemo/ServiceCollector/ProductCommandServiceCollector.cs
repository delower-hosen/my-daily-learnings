using Domain.Contracts;
using Microsoft.Extensions.DependencyInjection;
using Services.CommandServices;

namespace ServiceCollector
{
    public static class ProductCommandServiceCollector
    {
        public static void AddProductCommandServices(this IServiceCollection serviceCollection)
        {
            serviceCollection.AddScoped<ICreateProductCommandService, CreateProductCommandService>();
        }
    }
}
