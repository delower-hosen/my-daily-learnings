using EfCore.PostgreSql.DomainModels.Entities;
using Microsoft.EntityFrameworkCore;

namespace EfCore.PostgreSql
{
    public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
    {
        public DbSet<Product> Products { get; set; }
    }
}
