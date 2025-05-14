namespace Template_Method
{
    public abstract class ReportGeneratorTemplate
    {
        public void GenerateReport()
        {
            ConnectToDatabase();
            FetchData();
            FormatReport();
            GenerateFile();
        }

        private void ConnectToDatabase()
        {
            Console.WriteLine("Connecting to db");
        }
        private void FetchData()
        {
            Console.WriteLine("Fetching data from db");
        }
        protected abstract void FormatReport();
        protected abstract void GenerateFile();

    }
}
