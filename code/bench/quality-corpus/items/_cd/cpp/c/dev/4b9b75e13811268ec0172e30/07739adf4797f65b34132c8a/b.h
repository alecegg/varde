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

#ifdef _WIN32
#include <windows.h>
#ifdef ERROR
#undef ERROR
#endif
#else
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <sys/time.h>
#endif

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <algorithm>
#include <atomic>
#include <cinttypes>
#include <thread>  // NOLINT(build/c++11)

#include "absl/base/attributes.h"
#include "absl/base/config.h"
#include "absl/base/dynamic_annotations.h"
#include "absl/base/internal/atomic_hook.h"
#include "absl/base/internal/cycleclock.h"
#include "absl/base/internal/hide_ptr.h"
#include "absl/base/internal/low_level_alloc.h"
#include "absl/base/internal/raw_logging.h"
#include "absl/base/internal/spinlock.h"
#include "absl/base/internal/sysinfo.h"
#include "absl/base/internal/thread_identity.h"
#include "absl/base/port.h"
#include "absl/debugging/stacktrace.h"
#include "absl/debugging/symbolize.h"
#include "absl/synchronization/internal/graphcycles.h"
#include "absl/synchronization/internal/per_thread_sem.h"
#include "absl/time/time.h"

