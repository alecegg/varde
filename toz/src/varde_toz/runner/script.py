"""Run Toz JavaScript in the vendored QuickJS-NG WASI module."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

MAX_RECORD_COUNT = 10_000
MAX_RECORD_BYTES = 8 * 1024 * 1024
WASM = Path(__file__).with_name("quickjs-wasi-3.6.2.wasm")


@dataclass(frozen=True)
class Limits:
    timeout_ms: int = 5_000
    memory_bytes: int = 64 * 1024 * 1024
    max_output_bytes: int = 1024 * 1024
    max_text_bytes: int = 16 * 1024 * 1024
    max_stack_bytes: int = 1024 * 1024


class Outcome(Enum):
    OK = "ok"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    MEMORY_LIMIT = "memory_limit"
    OUTPUT_LIMIT = "output_limit"
    RECORD_LIMIT = "record_limit"


@dataclass
class RunResult:
    outcome: Outcome
    output: str = ""
    error: str = ""
    records: list[tuple[str, str]] | None = None
    commands_used: bool = False


def _read_string(caller, exports, value_ptr: int) -> str:
    size_ptr = exports["wasm_malloc"](caller, 4)
    try:
        data_ptr = exports["qjs_get_string_len"](caller, value_ptr, size_ptr)
        size = int.from_bytes(
            exports["memory"].read(caller, size_ptr, size_ptr + 4), "little"
        )
        data = bytes(exports["memory"].read(caller, data_ptr, data_ptr + size))
        exports["qjs_free_cstring"](caller, data_ptr)
        return data.decode("utf-8", "replace")
    finally:
        exports["wasm_free"](caller, size_ptr)


def _host_string(caller, exports, value: str) -> int:
    data = value.encode("utf-8")
    ptr = exports["wasm_malloc"](caller, len(data))
    exports["memory"].write(caller, data, ptr)
    try:
        return exports["qjs_new_string"](caller, ptr, len(data))
    finally:
        exports["wasm_free"](caller, ptr)


def _install_host_function(store, exports, name: str, arity: int = 1) -> None:
    memory = exports["memory"]
    name_bytes = name.encode() + b"\0"
    name_ptr = exports["wasm_malloc"](store, len(name_bytes))
    memory.write(store, name_bytes, name_ptr)
    function_ptr = exports["qjs_new_host_function"](store, name_ptr, len(name), arity)
    exports["wasm_free"](store, name_ptr)
    prop_ptr = exports["wasm_malloc"](store, len(name_bytes))
    memory.write(store, name_bytes, prop_ptr)
    exports["qjs_set_prop_string"](
        store, exports["qjs_get_global"](store), prop_ptr, function_ptr
    )
    exports["wasm_free"](store, prop_ptr)


def run_script(
    source: str,
    *,
    input_text: str = "",
    meta: dict | None = None,
    limits: Limits | None = None,
    command: Callable[[dict, float], dict] | None = None,
) -> tuple[Outcome, list[tuple[str, str]]]:
    result = run_detailed(
        source, input_text=input_text, meta=meta, limits=limits, command=command
    )
    return result.outcome, result.records or []


def run_detailed(
    source: str,
    *,
    input_text: str = "",
    meta: dict | None = None,
    limits: Limits | None = None,
    command: Callable[[dict, float], dict] | None = None,
) -> RunResult:
    # This import intentionally lives here: ordinary capture/query CLI startup
    # must not load Wasmtime.
    import wasmtime

    limits = limits or Limits()
    config = wasmtime.Config()
    config.epoch_interruption = True
    engine = wasmtime.Engine(config)
    module = wasmtime.Module.from_file(engine, WASM)
    deadline = time.monotonic() + limits.timeout_ms / 1000
    store = wasmtime.Store(engine)
    store.set_limits(memory_size=limits.memory_bytes)
    store.set_epoch_deadline(1)
    output = bytearray()
    records: list[tuple[str, str]] = []
    record_bytes = 0
    record_limit = False
    output_limit = False
    script_error = ""
    host_error = ""
    command_used = False
    linker = wasmtime.Linker(engine)
    linker.define_wasi()
    store.set_wasi(wasmtime.WasiConfig())

    def host_call(
        caller: Any,
        name_ptr: int,
        name_len: int,
        _this_ptr: int,
        argc: int,
        argv_ptr: int,
    ) -> int:
        nonlocal record_bytes, record_limit, output_limit, command_used, script_error
        exports = caller.get("memory")
        name = bytes(exports.read(caller, name_ptr, name_ptr + name_len)).decode()
        if name == "print":
            if argc != 1:
                raise RuntimeError(
                    "print host callback expected one serialized argument"
                )
            value_ptr = int.from_bytes(
                exports.read(caller, argv_ptr, argv_ptr + 4), "little"
            )
            values = json.loads(_read_string(caller, caller, value_ptr))
            line = " ".join(values).encode("utf-8") + b"\n"
            if line.startswith(b"\0VardeTozError:"):
                script_error = (
                    line[len(b"\0VardeTozError:") :]
                    .decode("utf-8", "replace")
                    .rstrip("\n")
                )
                return caller.get("qjs_get_undefined")(caller)
            if len(output) + len(line) > limits.max_output_bytes:
                output_limit = True
                engine.increment_epoch()
                return caller.get("qjs_get_undefined")(caller)
            output.extend(line)
            return caller.get("qjs_get_undefined")(caller)
        if argc != 1:
            raise RuntimeError(f"invalid {name} host call")
        value_ptr = int.from_bytes(
            exports.read(caller, argv_ptr, argv_ptr + 4), "little"
        )
        payload = json.loads(_read_string(caller, caller, value_ptr))
        if name == "host_record":
            kind = str(payload[0])
            encoded = json.dumps(payload[1], ensure_ascii=False, separators=(",", ":"))
            size = len(kind.encode()) + len(encoded.encode())
            if (
                len(records) >= MAX_RECORD_COUNT
                or record_bytes + size > MAX_RECORD_BYTES
            ):
                record_limit = True
                engine.increment_epoch()
                return caller.get("qjs_get_undefined")(caller)
            record_bytes += size
            records.append((kind, encoded))
            return caller.get("qjs_get_undefined")(caller)
        if name == "host_exec":
            command_used = True
            if command is None:
                return _host_string(
                    caller,
                    caller,
                    json.dumps({"error": "command execution is unavailable"}),
                )
            remaining = max(0.0, deadline - time.monotonic())
            try:
                response = command(payload, remaining)
            except Exception as exc:
                response = {"__error": str(exc)}
            return _host_string(
                caller,
                caller,
                json.dumps(response, ensure_ascii=False, separators=(",", ":")),
            )
        raise RuntimeError(f"unsupported host callback: {name}")

    def guarded_host_call(
        caller: Any,
        name_ptr: int,
        name_len: int,
        this_ptr: int,
        argc: int,
        argv_ptr: int,
    ) -> int:
        nonlocal host_error
        try:
            return host_call(caller, name_ptr, name_len, this_ptr, argc, argv_ptr)
        except Exception as exc:
            host_error = str(exc)
            return caller.get("qjs_get_undefined")(caller)

    defaults = {
        "host_call": host_call,
        "host_interrupt": lambda: 0,
        "host_promise_rejection": lambda *_: None,
        "host_module_normalize": lambda *_: 0,
        "host_module_load": lambda *_: 0,
        "host_get_timezone_offset": lambda *_: 0,
    }
    for imp in module.imports:
        if imp.module != "env" or imp.name is None:
            continue
        callback = guarded_host_call if imp.name == "host_call" else defaults[imp.name]
        func = wasmtime.Func(
            store,
            cast("wasmtime.FuncType", imp.type),
            callback,
            access_caller=imp.name == "host_call",
        )
        linker.define(store, imp.module, imp.name, func)
    instance = linker.instantiate(store, module)
    exports: Any = instance.exports(store)
    exports["_initialize"](store)
    exports["qjs_init"](store)
    exports["qjs_set_max_stack_size"](store, limits.max_stack_bytes)

    def set_string(name: str, value: str) -> None:
        data = value.encode()
        ptr = exports["wasm_malloc"](store, len(data) + 1)
        exports["memory"].write(store, data + b"\0", ptr)
        value_ptr = exports["qjs_new_string"](store, ptr, len(data))
        name_bytes = name.encode() + b"\0"
        name_ptr = exports["wasm_malloc"](store, len(name_bytes))
        exports["memory"].write(store, name_bytes, name_ptr)
        exports["qjs_set_prop_string"](
            store, exports["qjs_get_global"](store), name_ptr, value_ptr
        )
        exports["wasm_free"](store, name_ptr)
        exports["wasm_free"](store, ptr)

    set_string("__toz_input", input_text)
    set_string(
        "__toz_meta", json.dumps(meta or {}, ensure_ascii=False, separators=(",", ":"))
    )
    _install_host_function(store, exports, "print", 0)
    _install_host_function(store, exports, "host_exec")
    _install_host_function(store, exports, "host_record")
    bootstrap = """
const __input = __toz_input;
const __meta = JSON.parse(__toz_meta);
globalThis.__native_print = print;
globalThis.print = (...args) => __native_print(JSON.stringify(args.map(value =>
    value !== null && typeof value === 'object'
      ? JSON.stringify(value) : String(value))));
globalThis.vardeToz = {handle: Object.assign(
  {handle:'',label:'',bytes:0,lines:0,exitCode:null,stream:'stdout'}, __meta),
  eachLine(a,b) {
    const stream = typeof a === 'string' ? a : (__meta.stream || 'stdout');
    const cb = typeof a === 'function' ? a : b;
    if (typeof cb !== 'function') throw new Error('eachLine: expected a function');
    const text = __input;
    if ((stream === 'stderr') !== ((__meta.stream || 'stdout') === 'stderr') ||
        !text) return;
    const lines = text.split(/\\r?\\n/);
    if (text.endsWith('\\n')) lines.pop();
    for (const line of lines) cb(line);
  },
  text(stream) {
    if (stream && stream !== (__meta.stream || 'stdout')) return '';
    if (encodeURIComponent(__input).replace(/%[0-9A-F]{2}/gi, 'x').length >
        __TOZ_MAX_TEXT)
      throw new Error(
        'toz.text(): capture exceeds max_text_bytes; use toz.eachLine() instead');
    return __input;
  },
  record(kind,obj) { __toz_record(JSON.stringify([String(kind), obj])); },
  exec(request) {
    const response = JSON.parse(__toz_exec(JSON.stringify(request)));
    if (response.__error) throw new Error(response.__error);
    return response;
  }};
globalThis.toz = globalThis.vardeToz;
globalThis.console = {
  log: (...args) => print(...args),
  error: (...args) => print(...args)
};
function __toz_record(value) { return host_record(value); }
function __toz_exec(value) { return host_exec(value); }
"""
    _install_host_function(store, exports, "host_record")
    _install_host_function(store, exports, "host_exec")
    bootstrap = bootstrap.replace("__TOZ_MAX_TEXT", str(limits.max_text_bytes))
    sentinel = "\0VardeTozError:"
    code = (
        f"try {{ eval({json.dumps(bootstrap)}); eval({json.dumps(source)}); }} "
        f"catch (__toz_caught) {{ print({json.dumps(sentinel)} + "
        f"String(__toz_caught)); }}"
    ).encode()
    code_ptr = exports["wasm_malloc"](store, len(code) + 1)
    exports["memory"].write(store, code + b"\0", code_ptr)
    filename = b"<varde-toz>\0"
    filename_ptr = exports["wasm_malloc"](store, len(filename))
    exports["memory"].write(store, filename, filename_ptr)
    timer = threading.Timer(
        max(0.0, deadline - time.monotonic()), engine.increment_epoch
    )
    timer.start()
    try:
        value_ptr = exports["qjs_eval"](store, code_ptr, len(code), filename_ptr, 0)
        failed = bool(exports["qjs_is_exception"](store, value_ptr))
    except wasmtime.Trap as exc:
        if output_limit:
            return RunResult(Outcome.OUTPUT_LIMIT, records=[])
        if record_limit:
            return RunResult(Outcome.RECORD_LIMIT, records=[])
        if "interrupt" in str(exc).lower() or time.monotonic() >= deadline:
            return RunResult(Outcome.TIMEOUT, records=[])
        if "memory" in str(exc).lower() or "resource limit" in str(exc).lower():
            return RunResult(Outcome.MEMORY_LIMIT, records=[])
        return RunResult(Outcome.EXCEPTION, error=str(exc), records=[])
    finally:
        timer.cancel()
        try:
            exports["wasm_free"](store, code_ptr)
            exports["wasm_free"](store, filename_ptr)
        except wasmtime.Trap:
            pass
    if output_limit:
        return RunResult(Outcome.OUTPUT_LIMIT, records=[])
    if record_limit:
        return RunResult(Outcome.RECORD_LIMIT, records=[])
    if host_error:
        return RunResult(Outcome.EXCEPTION, error=host_error, records=[])
    if time.monotonic() >= deadline:
        return RunResult(Outcome.TIMEOUT, records=[])
    if failed:
        try:
            error = _read_string(store, exports, exports["qjs_get_exception"](store))
        except Exception:
            error = ""
        if "out of memory" in error.lower():
            return RunResult(Outcome.MEMORY_LIMIT, records=[])
        return RunResult(
            Outcome.EXCEPTION, error=error or "script raised an exception", records=[]
        )
    if script_error:
        if "out of memory" in script_error.lower():
            return RunResult(Outcome.MEMORY_LIMIT, records=[])
        return RunResult(Outcome.EXCEPTION, error=script_error, records=[])
    return RunResult(
        Outcome.OK,
        output.decode("utf-8", "replace"),
        records=records,
        commands_used=command_used,
    )
