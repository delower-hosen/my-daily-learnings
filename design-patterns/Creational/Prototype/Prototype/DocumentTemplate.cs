namespace Prototype
{
    public class DocumentTemplate : IPrototype<DocumentTemplate>
    {
        public string Title { get; set; }
        public string ContentBody { get; set; }
        public List<string> Tags { get; set; }
        public DocumentTemplate(string title, string contentBody, List<string> tags)
        {
            Title = title;
            ContentBody = contentBody;
            Tags = tags;
        }

        public DocumentTemplate Clone()
        {
            return new DocumentTemplate(Title, ContentBody, Tags);
        }

        public DocumentTemplate DeepClone()
        {
            return new DocumentTemplate(Title, ContentBody, new List<string>(Tags));
        }

        public override string ToString()
        {
            return $"Title: {Title}, Content: {ContentBody}, Tags: {string.Join(", ", Tags)}";
        }
    }
}
