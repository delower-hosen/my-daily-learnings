namespace Decorator
{
    public class TextDecorator : IText
    {
        protected readonly IText _text;

        protected TextDecorator(IText text)
        {
            _text = text;
        }

        public virtual string GetContent() => _text.GetContent();
    }
}
