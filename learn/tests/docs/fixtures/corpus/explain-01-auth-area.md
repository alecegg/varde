# How session validation works in auth

## Background

The auth module validates sessions for every request.

## Intuition

A request carries a token; the module checks it and either lets the request on or rejects it.

## How It Works

```ui
f = flow(title: "Session validation", step: [{"id": "tok", "text": "Read token", "next": ["look"]}, {"id": "look", "text": "Look up session", "next": ["ok", "bad"]}, {"id": "ok", "text": "Attach user"}, {"id": "bad", "text": "Reject with 401"}])
```
