namespace Template_Method
{
    public class PdfReportGenerator : ReportGeneratorTemplate
    {
        protected override void FormatReport()
        {
            Console.WriteLine("Formating data for pdf");
        }

        protected override void GenerateFile()
        {
            Console.WriteLine("Generating pdf file");
        }
    }
}
