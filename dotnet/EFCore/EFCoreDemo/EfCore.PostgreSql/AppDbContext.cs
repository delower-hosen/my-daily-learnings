using Microsoft.EntityFrameworkCore;
using Persistence.DomainModels.Entities;

namespace Persistence
{
    public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
    {
        public DbSet<Product> Products { get; set; }
    }
}
