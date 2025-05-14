namespace Abstract_Factory
{
    public class WindowsTextBox : ITextBox
    {
        public void Render()
        {
            Console.WriteLine("Rendering windows text box");
        }
    }
}
