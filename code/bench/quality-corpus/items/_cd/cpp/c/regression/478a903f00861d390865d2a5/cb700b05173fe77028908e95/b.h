// Copyright 2020 The Abseil Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//
// POSIX spec:
//   http://pubs.opengroup.org/onlinepubs/009695399/functions/fprintf.html
//
#include "absl/strings/internal/str_format/arg.h"

#include <cassert>
#include <cerrno>
#include <cstdlib>
#include <string>
#include <type_traits>

#include "absl/base/port.h"
#include "absl/strings/internal/str_format/float_conversion.h"
#include "absl/strings/numbers.h"

bool ConvertIntArg(T v, FormatConversionSpecImpl conv, FormatSinkImpl *sink) {
  using U = typename MakeUnsigned<T>::type;
  IntDigits as_digits;

  // This odd casting is due to a bug in -Wswitch behavior in gcc49 which causes
  // it to complain about a switch/case type mismatch, even though both are
  // FormatConverionChar.  Likely this is because at this point
  // FormatConversionChar is declared, but not defined.
  switch (static_cast<uint8_t>(conv.conversion_char())) {
    case static_cast<uint8_t>(FormatConversionCharInternal::c):
      return ConvertCharImpl(static_cast<char>(v), conv, sink);

    case static_cast<uint8_t>(FormatConversionCharInternal::o):
      as_digits.PrintAsOct(static_cast<U>(v));
      break;

    case static_cast<uint8_t>(FormatConversionCharInternal::x):
      as_digits.PrintAsHexLower(static_cast<U>(v));
      break;
    case static_cast<uint8_t>(FormatConversionCharInternal::X):
      as_digits.PrintAsHexUpper(static_cast<U>(v));
      break;

    case static_cast<uint8_t>(FormatConversionCharInternal::u):
      as_digits.PrintAsDec(static_cast<U>(v));
      break;

    case static_cast<uint8_t>(FormatConversionCharInternal::d):
    case static_cast<uint8_t>(FormatConversionCharInternal::i):
    case static_cast<uint8_t>(FormatConversionCharInternal::v):
      as_digits.PrintAsDec(v);
      break;

    case static_cast<uint8_t>(FormatConversionCharInternal::a):
    case static_cast<uint8_t>(FormatConversionCharInternal::e):
    case static_cast<uint8_t>(FormatConversionCharInternal::f):
    case static_cast<uint8_t>(FormatConversionCharInternal::g):
    case static_cast<uint8_t>(FormatConversionCharInternal::A):
    case static_cast<uint8_t>(FormatConversionCharInternal::E):
    case static_cast<uint8_t>(FormatConversionCharInternal::F):
    case static_cast<uint8_t>(FormatConversionCharInternal::G):
      return ConvertFloatImpl(static_cast<double>(v), conv, sink);

    default:
      ABSL_ASSUME(false);
  }

  if (conv.is_basic()) {
    sink->Append(as_digits.with_neg_and_zero());
    return true;
  }
  return ConvertIntImplInnerSlow(as_digits, conv, sink);
}