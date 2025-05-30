using System.Linq.Expressions;

namespace Persistence.Repositories
{
    public interface IRepository<T> where T : class
    {
        Task<T?> GetAsync(object id);
        Task<IEnumerable<T>> GetAllAsync();
        Task<IEnumerable<T>> FindAsync(Expression<Func<T, bool>> predicate);

        Task AddAsync(T entity);
        void Update(T entity);
        void Delete(T entity);

        Task<int> SaveChangesAsync();
    }
}
