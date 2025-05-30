using Command.Receivers;

namespace Command.Commands
{
    public class StereoOnWithCDCommand : ICommand
    {
        private readonly Stereo _stereo;
        public StereoOnWithCDCommand(Stereo stereo) => _stereo = stereo;

        public void Execute()
        {
            _stereo.On();
            _stereo.SetCD();
            _stereo.SetVolume(11);
        }
    }
}
