using Custom_DI_Container.Interfaces;

namespace Custom_DI_Container.Services
{
    public class Bar
    {
        private readonly IFoo _foo;

        public Bar(IFoo foo)
        {
            _foo = foo;
        }

        public void BarMethod()
        {
            Console.WriteLine("Bar called");
            _foo.FooMethod();
        }
    }

}
