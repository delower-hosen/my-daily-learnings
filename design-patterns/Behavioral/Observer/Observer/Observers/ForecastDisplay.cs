namespace Observer.Observers
{
    public class ForecastDisplay : IObserver
    {
        private float _lastPressure = 1013;

        public void Update(float temperature, float humidity, float pressure)
        {
            string forecast = pressure > _lastPressure
                ? "Improving weather on the way!"
                : pressure < _lastPressure
                    ? "Watch out for cooler, rainy weather."
                    : "More of the same.";
            Console.WriteLine($"[Forecast] {forecast}");
            _lastPressure = pressure;
        }
    }
}
