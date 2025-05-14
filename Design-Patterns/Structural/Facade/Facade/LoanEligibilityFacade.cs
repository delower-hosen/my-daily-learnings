namespace Facade
{
    public class LoanEligibilityFacade
    {
        private readonly CreditCardService _creditCardService;
        private readonly IncomeService _incomeService;
        private readonly DocumentService _documentService;
        public LoanEligibilityFacade()
        {
            _creditCardService = new CreditCardService();
            _incomeService = new IncomeService();
            _documentService = new DocumentService();
        }

        public bool IsEligible(string ssn)
        {
            bool creditOk = _creditCardService.HasGoodCreditScore(ssn);
            bool incomeOk = _incomeService.HasStableIncomeSource(ssn);
            bool docsOk = _documentService.AreDocumentsValid(ssn);

            return creditOk && incomeOk && docsOk;
        }
    }
}
