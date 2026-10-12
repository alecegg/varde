using System;

class WhenGuards
{
    static int SwitchGuard(object value)
    {
        switch (value)
        {
            case int n when n > 0:
                return n;
            default:
                return 0;
        }
    }

    static int CatchGuard()
    {
        try
        {
            throw new Exception();
        }
        catch (Exception error) when (error.Message.Length > 0)
        {
            return 1;
        }
        finally
        {
        }
    }

    static int SwitchArm(int value) => value switch
    {
        int n when n > 0 => n,
        _ => 0,
    };
}
