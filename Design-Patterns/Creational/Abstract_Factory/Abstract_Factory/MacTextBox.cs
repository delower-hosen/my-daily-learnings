namespace Abstract_Factory
{
    public class MacTextBox : ITextBox
    {
        public void Render()
        {
            Console.WriteLine("Rendering Mac text box");
        }
    }
}
