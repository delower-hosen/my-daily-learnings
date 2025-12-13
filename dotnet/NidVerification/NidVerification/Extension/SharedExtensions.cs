namespace NidVerification.Extension
{
    public static class SharedExtensions
    {
        public static double Median(this IEnumerable<double> source)
        {
            var sorted = from item in source
                         orderby item
                         select item;

            int count = sorted.Count();
            if (count % 2 == 0)
            {
                int midpoint = count / 2;
                return (sorted.ElementAt(midpoint - 1) + sorted.ElementAt(midpoint)) / 2;
            }
            else
            {
                return sorted.ElementAt(count / 2);
            }
        }
    }
}
