namespace Observer.Observers
{
    public class CurrentConditionsDisplay : IObserver
    {
        public void Update(float temperature, float humidity, float pressure)
        {
            Console.WriteLine($"[CurrentConditions] Temp: {temperature}°C, Humidity: {humidity}%, Pressure: {pressure} hPa");
        }
    }
}
