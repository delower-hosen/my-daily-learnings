namespace Abstract_Factory
{
    public class Client
    {
        private readonly IButton _button;
        private readonly ITextBox _textBox;
        public Client(IUIFactory uIFactory)
        {
            _button = uIFactory.CreateButton();
            _textBox = uIFactory.CreateTextBox();
        }

        public void RenderUI()
        {
            _button.Render();
            _textBox.Render();
        }
    }
}
