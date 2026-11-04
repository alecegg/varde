// SPDX-License-Identifier: MIT

public bool Equals(JValue other)
        {
            if (other == null)
            {
                return false;
            }

            return ValuesEquals(this, other);
        }

public override bool Equals(object obj)
        {
            if (obj == null)
            {
                return false;
            }

            JValue otherValue = obj as JValue;
            if (otherValue != null)
            {
                return Equals(otherValue);
            }

            return base.Equals(obj);
        }