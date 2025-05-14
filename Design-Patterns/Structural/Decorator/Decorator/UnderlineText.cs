namespace Decorator
{
    public class UnderlineText : TextDecorator
    {
        public UnderlineText(IText text) : base(text) { }

        public override string GetContent() => $"<u>{base.GetContent()}</u>";
    }
}
