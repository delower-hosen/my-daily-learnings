using Observer.Observers;
using Observer.Subject;

var weatherData = new WeatherData();

var currentDisplay = new CurrentConditionsDisplay();
var statsDisplay = new StatisticsDisplay();
var forecastDisplay = new ForecastDisplay();

weatherData.RegisterObserver(currentDisplay);
weatherData.RegisterObserver(statsDisplay);
weatherData.RegisterObserver(forecastDisplay);

weatherData.SetMeasurements(27, 65, 1012);
Console.WriteLine("---");
weatherData.SetMeasurements(28, 70, 1011);
Console.WriteLine("---");
weatherData.SetMeasurements(26, 90, 1013);