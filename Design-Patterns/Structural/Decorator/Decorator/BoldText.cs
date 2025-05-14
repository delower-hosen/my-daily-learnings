namespace Decorator
{
    public class BoldText : TextDecorator
    {
        public BoldText(IText text) : base(text) { }

        public override string GetContent() => $"<b>{base.GetContent()}</b>";
    }
}
