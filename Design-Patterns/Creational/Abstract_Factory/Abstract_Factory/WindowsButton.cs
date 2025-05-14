namespace Abstract_Factory
{
    public class WindowsButton : IButton
    {
        public void Render()
        {
            Console.WriteLine("Rendering windows button");
        }
    }
}
