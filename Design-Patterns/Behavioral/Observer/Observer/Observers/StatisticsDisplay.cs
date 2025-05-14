namespace Observer.Observers
{
    public class StatisticsDisplay : IObserver
    {
        private readonly List<float> _temperatureReadings = [];

        public void Update(float temperature, float humidity, float pressure)
        {
            _temperatureReadings.Add(temperature);
            float average = _temperatureReadings.Average();
            Console.WriteLine($"[Statistics] Avg Temp: {average:0.0}°C over {_temperatureReadings.Count} readings.");
        }
    }
}
