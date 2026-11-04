// Copyright 2017 The Abseil Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "absl/synchronization/mutex.h"

#ifdef WIN32
#include <windows.h>
#endif

#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <functional>
#include <memory>
#include <random>
#include <string>
#include <thread>  // NOLINT(build/c++11)
#include <vector>

#include "gtest/gtest.h"
#include "absl/base/internal/raw_logging.h"
#include "absl/base/internal/sysinfo.h"
#include "absl/memory/memory.h"
#include "absl/synchronization/internal/thread_pool.h"
#include "absl/time/clock.h"
#include "absl/time/time.h"

static void TestMu(TestContext *cxt, int c) {
  for (int i = 0; i != cxt->iterations; i++) {
    absl::MutexLock l(&cxt->mu);
    int a = cxt->g0 + 1;
    cxt->g0 = a;
    cxt->g1--;
  }
}

static void TestTry(TestContext *cxt, int c) {
  for (int i = 0; i != cxt->iterations; i++) {
    do {
      std::this_thread::yield();
    } while (!cxt->mu.TryLock());
    int a = cxt->g0 + 1;
    cxt->g0 = a;
    cxt->g1--;
    cxt->mu.Unlock();
  }
}

static void TestRW(TestContext *cxt, int c) {
  if ((c & 1) == 0) {
    for (int i = 0; i != cxt->iterations; i++) {
      absl::WriterMutexLock l(&cxt->mu);
      cxt->g0++;
      cxt->g1--;
      cxt->mu.AssertHeld();
      cxt->mu.AssertReaderHeld();
    }
  } else {
    for (int i = 0; i != cxt->iterations; i++) {
      absl::ReaderMutexLock l(&cxt->mu);
      ABSL_RAW_CHECK(cxt->g0 == -cxt->g1, "Error in TestRW");
      cxt->mu.AssertReaderHeld();
    }
  }
}

static int RunTest(void (*test)(TestContext *cxt, int), int threads,
                   int iterations, int operations) {
  TestContext cxt;
  return RunTestCommon(&cxt, test, threads, iterations, operations);
}

// Copyright 2017 The Abseil Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "absl/time/internal/test_util.h"

#include <algorithm>
#include <cstddef>
#include <cstring>

#include "absl/base/internal/raw_logging.h"
#include "cctz/zone_info_source.h"

