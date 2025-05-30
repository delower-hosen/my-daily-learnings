using Command.Receivers;

namespace Command.Commands
{
    public class GarageDoorOpenCommand : ICommand
    {
        private readonly GarageDoor _garageDoor;
        public GarageDoorOpenCommand(GarageDoor garageDoor) => _garageDoor = garageDoor;
        public void Execute() => _garageDoor.Open();
    }
}
