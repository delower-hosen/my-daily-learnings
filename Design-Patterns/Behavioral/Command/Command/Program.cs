// Receivers
using Command.Commands;
using Command.Invokers;
using Command.Receivers;

var light = new Light();
var garageDoor = new GarageDoor();
var stereo = new Stereo();

// Commands
var lightOn = new LightOnCommand(light);
var lightOff = new LightOffCommand(light);

var garageOpen = new GarageDoorOpenCommand(garageDoor);
var garageClose = new GarageDoorCloseCommand(garageDoor);

var stereoOn = new StereoOnWithCDCommand(stereo);
var stereoOff = new StereoOffCommand(stereo);

// Invoker
var remote = new RemoteControl();

// Use the remote to control different devices
remote.SetCommand(lightOn);
remote.PressButton(); // Light is ON

remote.SetCommand(garageOpen);
remote.PressButton(); // Garage Door is OPEN

remote.SetCommand(stereoOn);
remote.PressButton(); // Stereo is ON, CD set, Volume 11

remote.SetCommand(stereoOff);
remote.PressButton(); // Stereo is OFF