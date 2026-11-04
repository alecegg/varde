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
  SetInvariantChecked(false);
  cxt->mu.EnableInvariantDebugging(CheckSumG0G1, cxt);
  for (int i = 0; i != cxt->iterations; i++) {
    absl::MutexLock l(&cxt->mu);
    int a = cxt->g0 + 1;
    cxt->g0 = a;
    cxt->g1--;
  }
}

static void TestTry(TestContext *cxt, int c) {
  SetInvariantChecked(false);
  cxt->mu.EnableInvariantDebugging(CheckSumG0G1, cxt);
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
  SetInvariantChecked(false);
  cxt->mu.EnableInvariantDebugging(CheckSumG0G1, cxt);
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
  absl::Mutex mu2;
  absl::CondVar cv2;
  int c0;
  int c1;

  // run with large thread count for full test and to get timing

#if !defined(ABSL_MUTEX_ENABLE_INVARIANT_DEBUGGING_NOT_IMPLEMENTED)
  absl::EnableMutexInvariantDebugging(false);
#endif
  c0 = 0;
  c1 = 0;
  cxt.g0 = 0;
  cxt.g1 = 0;
  cxt.iterations = iterations;
  cxt.threads = threads;
  absl::synchronization_internal::ThreadPool tp(threads);
  for (int i = 0; i != threads; i++) {
    tp.Schedule(std::bind(&EndTest, &c0, &c1, &mu2, &cv2,
                          std::function<void(int)>(
                              std::bind(test, &cxt, std::placeholders::_1))));
  }
  mu2.Lock();
  while (c1 != threads) {
    cv2.Wait(&mu2);
  }
  mu2.Unlock();
  int saved_g0 = cxt.g0;

  // run again with small number of iterations to test invariant checking

#if !defined(ABSL_MUTEX_ENABLE_INVARIANT_DEBUGGING_NOT_IMPLEMENTED)
  absl::EnableMutexInvariantDebugging(true);
#endif
  SetInvariantChecked(true);
  c0 = 0;
  c1 = 0;
  cxt.g0 = 0;
  cxt.g1 = 0;
  cxt.iterations = (iterations > 10 ? 10 : iterations);
  cxt.threads = threads;
  for (int i = 0; i != threads; i++) {
    tp.Schedule(std::bind(&EndTest, &c0, &c1, &mu2, &cv2,
                          std::function<void(int)>(
                              std::bind(test, &cxt, std::placeholders::_1))));
  }
  mu2.Lock();
  while (c1 != threads) {
    cv2.Wait(&mu2);
  }
  mu2.Unlock();
#if !defined(ABSL_MUTEX_ENABLE_INVARIANT_DEBUGGING_NOT_IMPLEMENTED)
  ABSL_RAW_CHECK(GetInvariantChecked(), "Invariant not checked");
#endif

  return saved_g0;
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

