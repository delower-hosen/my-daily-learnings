﻿using Command.Receivers;

namespace Command.Commands
{
    public class GarageDoorCloseCommand : ICommand
    {
        private readonly GarageDoor _garageDoor;
        public GarageDoorCloseCommand(GarageDoor garageDoor) => _garageDoor = garageDoor;
        public void Execute() => _garageDoor.Close();
    }
}
