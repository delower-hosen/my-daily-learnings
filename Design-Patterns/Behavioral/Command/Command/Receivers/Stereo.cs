namespace Command.Receivers
{
    public class Stereo
    {
        public void On() => Console.WriteLine("Stereo is ON");
        public void Off() => Console.WriteLine("Stereo is OFF");
        public void SetCD() => Console.WriteLine("Stereo is set to CD");
        public void SetVolume(int volume) => Console.WriteLine($"Stereo volume set to {volume}");
    }
}
