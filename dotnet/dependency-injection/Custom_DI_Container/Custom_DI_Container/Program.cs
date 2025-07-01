using Custom_DI_Container.Interfaces;
using Custom_DI_Container.Services;
using Custom_DI_Container;

var container = new SimpleServiceProvider();

// Register services
container.Register<IFoo, Foo>(ServiceLifetime.Singleton);
container.Register<Bar>(ServiceLifetime.Transient);

// Resolve and use
var bar1 = container.GetService<Bar>();
bar1.BarMethod();

var bar2 = container.GetService<Bar>();
Console.WriteLine(ReferenceEquals(bar1, bar2)); // False because Bar is transient

var foo1 = container.GetService<IFoo>();
var foo2 = container.GetService<IFoo>();
Console.WriteLine(ReferenceEquals(foo1, foo2)); // True because Foo is singleton