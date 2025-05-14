using Singleton;

var s1 = SingletonService.Instance;
var s2 = SingletonService.Instance;

s1.ShowMessage();

Console.WriteLine(ReferenceEquals(s1, s2));