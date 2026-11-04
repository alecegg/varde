/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

static int indexOf(CharSequence cs, int searchChar, int start) {
        if (cs instanceof String) {
            return ((String) cs).indexOf(searchChar, start);
        } else {
            int sz = cs.length();
            if (start < 0) {
                start = 0;
            }
            for (int i = start; i < sz; i++) {
                if (cs.charAt(i) == searchChar) {
                    return i;
                }
            }
            return -1;
        }
    }

static int indexOf(CharSequence cs, CharSequence searchChar, int start) {
        if (cs instanceof String && searchChar instanceof String) {
            // TODO: Do we assume searchChar is usually relatively small;
            //       If so then calling toString() on it is better than reverting to
            //       the green implementation in the else block
            return ((String) cs).indexOf((String) searchChar, start);
        } else {
            // TODO: Implement rather than convert to String
            return cs.toString().indexOf(searchChar.toString(), start);
        }
    }

static int lastIndexOf(CharSequence cs, int searchChar, int start) {
        if (cs instanceof String) {
            return ((String) cs).lastIndexOf(searchChar, start);
        } else {
            int sz = cs.length();
            if (start < 0) {
                return -1;
            }
            if (start >= sz) {
                start = sz - 1;
            }
            for (int i = start; i >= 0; --i) {
                if (cs.charAt(i) == searchChar) {
                    return i;
                }
            }
            return -1;
        }
    }

static int lastIndexOf(CharSequence cs, CharSequence searchChar, int start) {
        if (cs instanceof String && searchChar instanceof String) {
            // TODO: Do we assume searchChar is usually relatively small;
            //       If so then calling toString() on it is better than reverting to
            //       the green implementation in the else block
            return ((String) cs).lastIndexOf((String) searchChar, start);
        } else {
            // TODO: Implement rather than convert to String
            return cs.toString().lastIndexOf(searchChar.toString(), start);
        }
    }