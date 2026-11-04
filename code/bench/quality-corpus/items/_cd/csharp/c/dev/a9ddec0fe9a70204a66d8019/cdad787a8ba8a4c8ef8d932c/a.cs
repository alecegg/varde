// SPDX-License-Identifier: MIT

internal static bool CanConvertPrimitive(Type from, Type to)
        {
            if (from == to)
            {
                // same type
                return true;
            }

            int fromMask = 0, toMask = 0;

            for (int i = 0; i < PrimitiveTypes.Length && (fromMask == 0 || toMask == 0); i++)
            {
                if (PrimitiveTypes[i] == from)
                {
                    fromMask = WideningMasks[i];
                }
                else if (PrimitiveTypes[i] == to)
                {
                    toMask = 1 << i;
                }
            }

            return (fromMask & toMask) != 0;
        }

private static bool FilterParameters(ParameterInfo[] parameters, IList<Type> types, bool enableParamArray)
        {
            if (parameters == null)
            {
                throw new ArgumentNullException(nameof(parameters));
            }
            if (types == null)
            {
                throw new ArgumentNullException(nameof(types));
            }
            if (parameters.Length == 0)
            {
                // fast check for parameterless methods
                return types.Count == 0;
            }
            if (parameters.Length > types.Count)
            {
                // not all declared parameters were specified (optional parameters are not supported)
                return false;
            }

            // check if the last parameter is ParamArray
            Type paramArrayType = null;

            if (enableParamArray)
            {
                ParameterInfo lastParam = parameters[parameters.Length - 1];
                if (lastParam.ParameterType.IsArray && lastParam.IsDefined(typeof(ParamArrayAttribute)))
                {
                    paramArrayType = lastParam.ParameterType.GetElementType();
                }
            }

            if (paramArrayType == null && parameters.Length != types.Count)
            {
                // when there's no ParamArray, number of parameters should match
                return false;
            }

            for (int i = 0; i < types.Count; i++)
            {
                Type paramType = (paramArrayType != null && i >= parameters.Length - 1) ? paramArrayType : parameters[i].ParameterType;

                if (paramType == types[i])
                {
                    // exact match with provided type
                    continue;
                }

                if (paramType == typeof(object))
                {
                    // parameter of type object matches anything
                    continue;
                }

                if (paramType.IsPrimitive())
                {
                    if (!types[i].IsPrimitive() || !CanConvertPrimitive(types[i], paramType))
                    {
                        // primitive parameter can only be assigned from compatible primitive type
                        return false;
                    }
                }
                else
                {
                    if (!paramType.IsAssignableFrom(types[i]))
                    {
                        return false;
                    }
                }
            }

            return true;
        }

public ParametersMatchComparer(IList<Type> types, bool enableParamArray)
            {
                if (types == null)
                {
                    throw new ArgumentNullException(nameof(types));
                }

                _types = types;
                _enableParamArray = enableParamArray;
            }