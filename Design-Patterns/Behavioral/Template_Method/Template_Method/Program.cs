using Template_Method;

var pdfReport = new PdfReportGenerator();
pdfReport.GenerateReport();

var csvReport = new CsvReportGenerator();
csvReport.GenerateReport();