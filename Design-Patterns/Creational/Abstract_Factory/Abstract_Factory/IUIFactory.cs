namespace Abstract_Factory
{
    public interface IUIFactory
    {
        public IButton CreateButton();
        public ITextBox CreateTextBox();
    }
}
