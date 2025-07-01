using Custom_DI_Container.Interfaces;

namespace Custom_DI_Container.Services
{
    public class Foo : IFoo
    {
        public void FooMethod() => Console.WriteLine("Foo called");
    }
}
