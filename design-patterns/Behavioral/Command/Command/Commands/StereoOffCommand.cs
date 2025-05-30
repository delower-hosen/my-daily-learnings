using Command.Receivers;

namespace Command.Commands
{
    public class StereoOffCommand : ICommand
    {
        private readonly Stereo _stereo;
        public StereoOffCommand(Stereo stereo) => _stereo = stereo;
        public void Execute() => _stereo.Off();
    }
}
