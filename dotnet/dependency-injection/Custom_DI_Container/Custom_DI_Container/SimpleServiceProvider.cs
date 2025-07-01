namespace Custom_DI_Container
{
    public class SimpleServiceProvider
    {
        private readonly Dictionary<Type, ServiceDescriptor> _services = new();
        private readonly Dictionary<Type, object> _singletonInstances = new();

        // Register a service
        public void Register<TService, TImplementation>(ServiceLifetime lifetime)
        {
            _services[typeof(TService)] = new ServiceDescriptor(typeof(TService), typeof(TImplementation), lifetime);
        }

        // Register concrete type without interface
        public void Register<TService>(ServiceLifetime lifetime)
        {
            Register<TService, TService>(lifetime);
        }

        // Resolve a service
        public object GetService(Type serviceType)
        {
            if (!_services.TryGetValue(serviceType, out var descriptor))
            {
                if (!serviceType.IsAbstract)
                    return CreateInstance(serviceType);
                throw new Exception($"Service of type {serviceType.Name} is not registered");
            }

            if (descriptor.Lifetime == ServiceLifetime.Singleton)
            {
                if (descriptor.ImplementationInstance == null)
                {
                    descriptor.ImplementationInstance = CreateInstance(descriptor.ImplementationType);
                }
                return descriptor.ImplementationInstance;
            }

            return CreateInstance(descriptor.ImplementationType);
        }

        public T GetService<T>() => (T)GetService(typeof(T));

        // Create instance and resolve constructor dependencies recursively
        private object CreateInstance(Type implementationType)
        {
            var constructor = implementationType.GetConstructors().OrderByDescending(c => c.GetParameters().Length).First();

            var parameters = constructor.GetParameters()
                .Select(p => GetService(p.ParameterType))
                .ToArray();

            return Activator.CreateInstance(implementationType, parameters)!;
        }
    }
}
