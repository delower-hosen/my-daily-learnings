using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace EfCore.PostgreSql
{
    public class AppDbContextFactory : IDesignTimeDbContextFactory<AppDbContext>
    {
        public AppDbContext CreateDbContext(string[] args)
        {
            // Use the first CLI arg, or fallback to env var
            var connectionString = args.FirstOrDefault()
                ?? Environment.GetEnvironmentVariable("EFCORE_CONNECTION_STRING")
                ?? throw new InvalidOperationException("Connection string must be provided.");

            var optionsBuilder = new DbContextOptionsBuilder<AppDbContext>();
            optionsBuilder.UseNpgsql(connectionString);

            return new AppDbContext(optionsBuilder.Options);
        }
    }
}
