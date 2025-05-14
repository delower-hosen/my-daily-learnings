namespace Facade
{
    public class LoanApplicationClient
    {
        public bool IsEligibleForLoan(string ssn)
        {
            //var creditCardService = new CreditCardService();
            //var incomeService = new IncomeService();
            //var documentService = new DocumentService();

            //bool creditOk = creditCardService.HasGoodCreditScore(ssn);
            //bool incomeOk = incomeService.HasStableIncomeSource(ssn);
            //bool docsOk = documentService.AreDocumentsValid(ssn);

            //return creditOk && incomeOk && docsOk;

            var facade = new LoanEligibilityFacade();

            return facade.IsEligible(ssn);
        }
    }
}
