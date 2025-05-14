namespace Prototype
{
    public interface IPrototype<T>
    {
        T Clone();
        T DeepClone();
    }
}
