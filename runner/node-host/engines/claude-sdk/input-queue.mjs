// Async iterable of SDK user messages for streaming input.

export function userMessage(text) {
  return { type: "user", message: { role: "user", content: text }, parent_tool_use_id: null };
}

export class InputQueue {
  #items = [];
  #waiters = [];
  #closed = false;

  push(item) {
    if (this.#closed) return false;
    const waiter = this.#waiters.shift();
    if (waiter) waiter({ value: item, done: false });
    else this.#items.push(item);
    return true;
  }

  close() {
    this.#closed = true;
    for (const waiter of this.#waiters.splice(0)) waiter({ value: undefined, done: true });
  }

  [Symbol.asyncIterator]() {
    return {
      next: () => {
        if (this.#items.length > 0) return Promise.resolve({ value: this.#items.shift(), done: false });
        if (this.#closed) return Promise.resolve({ value: undefined, done: true });
        return new Promise((resolve) => this.#waiters.push(resolve));
      },
      return: () => {
        this.close();
        return Promise.resolve({ value: undefined, done: true });
      },
    };
  }
}
