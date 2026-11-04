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
            return Equals(obj as JValue);
        }