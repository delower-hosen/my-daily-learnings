namespace Decorator
{
    public class ItalicText : TextDecorator
    {
        public ItalicText(IText text) : base(text) { }

        public override string GetContent() => $"<i>{base.GetContent()}</i>";
    }
}
