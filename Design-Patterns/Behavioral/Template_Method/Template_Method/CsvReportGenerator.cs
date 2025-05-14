namespace Template_Method
{
    public class CsvReportGenerator : ReportGeneratorTemplate
    {
        protected override void FormatReport()
        {
            Console.WriteLine("Formatting data for csv");
        }

        protected override void GenerateFile()
        {
            Console.WriteLine("Generating csv file");
        }
    }
}
