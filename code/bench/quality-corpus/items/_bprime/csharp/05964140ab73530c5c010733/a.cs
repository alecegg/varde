using System.Text;

public static class Solution
{
    public static string Row(string[] cells, int width)
    {
        StringBuilder line = new StringBuilder();
        for (int index = 0; index < cells.Length; index++)
        {
            if (index > 0)
            {
                line.Append(" | ");
            }
            line.Append(cells[index].PadRight(width));
        }
        return line.ToString();
    }
}
