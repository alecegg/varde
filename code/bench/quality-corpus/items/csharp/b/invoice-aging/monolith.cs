public static class Solution
{
    public record Invoice(string Id, int DaysOverdue, decimal Balance);

    public record Line(string Id, string Bucket, decimal Fee);

    public record Report(Line[] Invoices, decimal[] Totals);

    /// <summary>Build the aging report: each invoice's bucket, fee, and totals.</summary>
    public static Report solution(Invoice[] invoices)
    {
        if (invoices == null)
        {
            throw new System.ArgumentException("invalid invoice");
        }
        if (invoices.Length > 1000)
        {
            throw new System.ArgumentException("invalid invoice");
        }
        var seen = new System.Collections.Generic.HashSet<string>();
        for (int index = 0; index < invoices.Length; index++)
        {
            Invoice invoice = invoices[index];
            if (invoice == null)
            {
                throw new System.ArgumentException("invalid invoice");
            }
            if (invoice.Id == null || invoice.Id.Length == 0)
            {
                throw new System.ArgumentException("invalid invoice");
            }
            bool ascii = true;
            foreach (char letter in invoice.Id)
            {
                if (letter > 127)
                {
                    ascii = false;
                }
            }
            if (!ascii)
            {
                throw new System.ArgumentException("invalid invoice");
            }
            if (!seen.Add(invoice.Id))
            {
                throw new System.ArgumentException("invalid invoice");
            }
            if (invoice.Balance < 0m)
            {
                throw new System.ArgumentException("invalid invoice");
            }
            if (invoice.Balance > 1_000_000m)
            {
                throw new System.ArgumentException("invalid invoice");
            }
        }
        var places = new int[invoices.Length];
        for (int index = 0; index < invoices.Length; index++)
        {
            int days = invoices[index].DaysOverdue;
            int place;
            if (days <= 0)
            {
                place = 0;
            }
            else if (days <= 30)
            {
                place = 1;
            }
            else if (days <= 60)
            {
                place = 2;
            }
            else if (days <= 90)
            {
                place = 3;
            }
            else
            {
                place = 4;
            }
            places[index] = place;
        }
        var order = new int[invoices.Length];
        for (int index = 0; index < invoices.Length; index++)
        {
            order[index] = index;
        }
        for (int left = 0; left < order.Length; left++)
        {
            for (int right = left + 1; right < order.Length; right++)
            {
                string held = invoices[order[left]].Id;
                string other = invoices[order[right]].Id;
                if (string.CompareOrdinal(held, other) > 0)
                {
                    int swap = order[left];
                    order[left] = order[right];
                    order[right] = swap;
                }
            }
        }
        var rows = new Line[invoices.Length];
        decimal[] totals = { 0m, 0m, 0m, 0m, 0m };
        for (int index = 0; index < order.Length; index++)
        {
            Invoice invoice = invoices[order[index]];
            int place = places[order[index]];
            string bucket;
            decimal rate;
            if (place == 0)
            {
                bucket = "current";
                rate = 0m;
            }
            else if (place == 1)
            {
                bucket = "1-30";
                rate = 0.02m;
            }
            else if (place == 2)
            {
                bucket = "31-60";
                rate = 0.05m;
            }
            else if (place == 3)
            {
                bucket = "61-90";
                rate = 0.08m;
            }
            else
            {
                bucket = "over-90";
                rate = 0.10m;
            }
            decimal fee = decimal.Round(
                invoice.Balance * rate, 2, System.MidpointRounding.AwayFromZero);
            rows[index] = new Line(invoice.Id, bucket, fee);
            if (place == 0)
            {
                totals[0] = totals[0] + invoice.Balance;
            }
            else if (place == 1)
            {
                totals[1] = totals[1] + invoice.Balance;
            }
            else if (place == 2)
            {
                totals[2] = totals[2] + invoice.Balance;
            }
            else if (place == 3)
            {
                totals[3] = totals[3] + invoice.Balance;
            }
            else
            {
                totals[4] = totals[4] + invoice.Balance;
            }
        }
        for (int place = 0; place < totals.Length; place++)
        {
            totals[place] = decimal.Round(totals[place], 2, System.MidpointRounding.AwayFromZero);
        }
        return new Report(rows, totals);
    }
}
