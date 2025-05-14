namespace Command.Invokers
{
    public class RemoteControl
    {
        private ICommand _command;
        public void SetCommand(ICommand command) => _command = command;
        public void PressButton() => _command.Execute();
    }
}
