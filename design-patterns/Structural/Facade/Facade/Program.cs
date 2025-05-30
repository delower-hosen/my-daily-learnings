using Facade;

var loanApplicationClient = new LoanApplicationClient();

var isEligibleForLoan = loanApplicationClient.IsEligibleForLoan("123");

Console.WriteLine(isEligibleForLoan
    ? "Eligible for Loan"
    : "Not eligible for Loan");