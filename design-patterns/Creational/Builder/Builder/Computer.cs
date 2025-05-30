namespace Builder
{
    public class Computer
    {
        public string CPU { get; private set; }
        public string RAM { get; private set; }
        public string Storage { get; private set; }
        public bool HasGraphicsCard { get; private set; }
        public bool HasWiFi { get; private set; }

        private Computer() { }

        public override string ToString()
        {
            return $"Computer with {CPU}, {RAM} RAM, {Storage} storage, " +
                   $"{(HasGraphicsCard ? "Graphics Card" : "No Graphics Card")}, " +
                   $"{(HasWiFi ? "WiFi" : "No WiFi")}.";
        }

        public class Builder
        {
            private readonly Computer _computer = new();

            public Builder SetCPU(string cpu)
            {
                _computer.CPU = cpu;
                return this;
            }

            public Builder SetRAM(string ram)
            {
                _computer.RAM = ram;
                return this;
            }

            public Builder SetStorage(string storage)
            {
                _computer.Storage = storage;
                return this;
            }

            public Builder AddGraphicsCard()
            {
                _computer.HasGraphicsCard = true;
                return this;
            }

            public Builder AddWiFi()
            {
                _computer.HasWiFi = true;
                return this;
            }

            public Computer Build()
            {
                return _computer;
            }
        }
    }

}
