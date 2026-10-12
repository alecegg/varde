//! Order-preserving edits to one event array in a hook-config JSON document.

use indexmap::IndexMap;
use serde::{
    Deserialize, Serialize,
    de::{self, MapAccess, SeqAccess, Visitor},
    ser::{SerializeMap, SerializeSeq},
};
use serde_json::value::RawValue;

type Object = IndexMap<String, Box<RawValue>>;
type RawEntries = Vec<Entry>;

/// A hook entry: untouched entries keep their source text; edited or inserted
/// entries are re-encoded.
enum Entry {
    Raw(Box<RawValue>),
    Ordered(OrderedValue),
}

enum OrderedValue {
    Null,
    Bool(bool),
    Number(serde_json::Number),
    String(String),
    Array(Vec<OrderedValue>),
    Object(IndexMap<String, OrderedValue>),
}

impl Serialize for OrderedValue {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        match self {
            Self::Null => serializer.serialize_unit(),
            Self::Bool(value) => serializer.serialize_bool(*value),
            Self::Number(value) => value.serialize(serializer),
            Self::String(value) => serializer.serialize_str(value),
            Self::Array(values) => {
                let mut sequence = serializer.serialize_seq(Some(values.len()))?;
                for value in values {
                    sequence.serialize_element(value)?;
                }
                sequence.end()
            }
            Self::Object(values) => {
                let mut map = serializer.serialize_map(Some(values.len()))?;
                for (key, value) in values {
                    map.serialize_entry(key, value)?;
                }
                map.end()
            }
        }
    }
}

impl<'de> Deserialize<'de> for OrderedValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        struct OrderedValueVisitor;

        impl<'de> Visitor<'de> for OrderedValueVisitor {
            type Value = OrderedValue;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("a JSON value")
            }

            fn visit_unit<E>(self) -> Result<Self::Value, E> {
                Ok(OrderedValue::Null)
            }

            fn visit_none<E>(self) -> Result<Self::Value, E> {
                Ok(OrderedValue::Null)
            }

            fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
                Ok(OrderedValue::Bool(value))
            }

            fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
                Ok(OrderedValue::Number(value.into()))
            }

            fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
                Ok(OrderedValue::Number(value.into()))
            }

            fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                serde_json::Number::from_f64(value)
                    .map(OrderedValue::Number)
                    .ok_or_else(|| E::custom("non-finite JSON number"))
            }

            fn visit_str<E>(self, value: &str) -> Result<Self::Value, E> {
                Ok(OrderedValue::String(value.to_owned()))
            }

            fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
                Ok(OrderedValue::String(value))
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut values = Vec::new();
                while let Some(value) = sequence.next_element()? {
                    values.push(value);
                }
                Ok(OrderedValue::Array(values))
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut values = IndexMap::new();
                while let Some((key, value)) = map.next_entry()? {
                    values.insert(key, value);
                }
                Ok(OrderedValue::Object(values))
            }
        }

        deserializer.deserialize_any(OrderedValueVisitor)
    }
}

/// Optional behavior for removing hook commands.
#[derive(Clone, Copy, Default)]
pub struct RemoveOptions {
    /// Remove the top-level `hooks` object when the final event is removed.
    pub prune_empty_hooks: bool,
}

/// Append one hook entry to `hooks.<event>`.
pub fn append_entry<E: Serialize>(
    input: &str,
    event: &str,
    entry: &E,
) -> Result<String, serde_json::Error> {
    let entry = Entry::Ordered(ordered_entry(entry)?);
    edit_event(input, event, true, false, |entries| {
        entries.push(entry);
        Ok((true, Vec::new()))
    })
    .map(|(text, _)| text)
}

/// Remove command entries whose command string matches `predicate`.
///
/// Commands inside a group's `hooks` array are removed individually so foreign
/// siblings in the same group remain intact. The returned strings are the
/// removed command values, in document order.
pub fn remove_matching_commands<F>(
    input: &str,
    event: &str,
    predicate: F,
) -> Result<(String, Vec<String>), serde_json::Error>
where
    F: FnMut(&str) -> bool,
{
    remove_matching_commands_with_options(input, event, predicate, RemoveOptions::default())
}

/// Remove matching commands, optionally pruning an empty top-level `hooks` object.
pub fn remove_matching_commands_with_options<F>(
    input: &str,
    event: &str,
    mut predicate: F,
    options: RemoveOptions,
) -> Result<(String, Vec<String>), serde_json::Error>
where
    F: FnMut(&str) -> bool,
{
    edit_event(input, event, false, options.prune_empty_hooks, |entries| {
        let mut removed = Vec::new();
        let mut changed = false;
        let mut kept = Vec::with_capacity(entries.len());
        for entry in entries.drain(..) {
            match remove_from_entry(entry, &mut predicate, &mut removed)? {
                Some((entry, entry_changed)) => {
                    kept.push(entry);
                    changed |= entry_changed;
                }
                None => changed = true,
            }
        }
        *entries = kept;
        Ok((changed, removed))
    })
}

/// Remove owned commands from one event, then append their replacement entries.
pub fn replace_owned_entries<F, E>(
    input: &str,
    event: &str,
    predicate: F,
    replacements: &[E],
) -> Result<(String, Vec<String>), serde_json::Error>
where
    F: FnMut(&str) -> bool,
    E: Serialize,
{
    let replacement_entries = replacements
        .iter()
        .map(|entry| ordered_entry(entry).map(Entry::Ordered))
        .collect::<Result<Vec<_>, _>>()?;
    replace_event_entries(input, event, predicate, replacement_entries)
}

/// Replace owned commands using entries read from an ordered JSON document.
/// The raw document is decoded into insertion-ordered objects before pretty
/// printing so replacement field order survives without `preserve_order`.
pub fn replace_owned_entries_from_json<F>(
    input: &str,
    event: &str,
    predicate: F,
    replacements_json: &str,
    replacements_event: &str,
) -> Result<(String, Vec<String>), serde_json::Error>
where
    F: FnMut(&str) -> bool,
{
    let replacement_entries = ordered_entries_from_json(replacements_json, replacements_event)?;
    replace_event_entries(input, event, predicate, replacement_entries)
}

fn replace_event_entries<F>(
    input: &str,
    event: &str,
    mut predicate: F,
    replacement_entries: RawEntries,
) -> Result<(String, Vec<String>), serde_json::Error>
where
    F: FnMut(&str) -> bool,
{
    edit_event(
        input,
        event,
        !replacement_entries.is_empty(),
        false,
        |entries| {
            let mut removed = Vec::new();
            let mut changed = false;
            let mut kept = Vec::with_capacity(entries.len() + replacement_entries.len());
            for entry in entries.drain(..) {
                match remove_from_entry(entry, &mut predicate, &mut removed)? {
                    Some((entry, entry_changed)) => {
                        kept.push(entry);
                        changed |= entry_changed;
                    }
                    None => changed = true,
                }
            }
            changed |= !replacement_entries.is_empty();
            kept.extend(replacement_entries);
            *entries = kept;
            Ok((changed, removed))
        },
    )
}

fn ordered_entry<E: Serialize>(entry: &E) -> Result<OrderedValue, serde_json::Error> {
    let json = serde_json::to_string(entry)?;
    serde_json::from_str(&json)
}

fn ordered_entries_from_json(input: &str, event: &str) -> Result<RawEntries, serde_json::Error> {
    let root: Object = serde_json::from_str(input)?;
    let Some(hooks_raw) = root.get("hooks") else {
        return Ok(Vec::new());
    };
    let hooks: Object = serde_json::from_str(hooks_raw.get())?;
    let Some(entries_raw) = hooks.get(event) else {
        return Ok(Vec::new());
    };
    let entries: Vec<Box<RawValue>> = serde_json::from_str(entries_raw.get())?;
    entries
        .iter()
        .map(|entry| serde_json::from_str(entry.get()).map(Entry::Ordered))
        .collect()
}

fn edit_event<F>(
    input: &str,
    event: &str,
    create_event: bool,
    prune_empty_hooks: bool,
    edit: F,
) -> Result<(String, Vec<String>), serde_json::Error>
where
    F: FnOnce(&mut RawEntries) -> Result<(bool, Vec<String>), serde_json::Error>,
{
    let empty = "{}";
    let source = if input.trim().is_empty() {
        empty
    } else {
        input
    };
    let mut root: Object = serde_json::from_str(source)?;
    let Some(hooks_raw) = root.get("hooks") else {
        if !create_event {
            return Ok((input.to_owned(), Vec::new()));
        }
        let mut hooks = IndexMap::<String, Box<RawValue>>::new();
        let mut entries = Vec::new();
        let (changed, removed) = edit(&mut entries)?;
        if !changed {
            return Ok((input.to_owned(), removed));
        }
        hooks.insert(event.to_owned(), raw_entries_pretty(&entries, 4)?);
        return render(root, hooks).map(|text| (text, removed));
    };

    let mut hooks: Object = serde_json::from_str(hooks_raw.get())?;
    let Some(entries_raw) = hooks.get(event) else {
        if !create_event {
            return Ok((input.to_owned(), Vec::new()));
        }
        let mut entries = Vec::new();
        let (changed, removed) = edit(&mut entries)?;
        if !changed {
            return Ok((input.to_owned(), removed));
        }
        hooks.insert(event.to_owned(), raw_entries_pretty(&entries, 4)?);
        return render(root, hooks).map(|text| (text, removed));
    };

    let entries: Vec<Box<RawValue>> = serde_json::from_str(entries_raw.get())?;
    let mut entries: RawEntries = entries.into_iter().map(Entry::Raw).collect();
    let (changed, removed) = edit(&mut entries)?;
    if !changed {
        return Ok((input.to_owned(), removed));
    }
    if entries.is_empty() {
        hooks.shift_remove(event);
    } else {
        hooks.insert(event.to_owned(), raw_entries_pretty(&entries, 4)?);
    }
    if prune_empty_hooks && hooks.is_empty() {
        root.shift_remove("hooks");
        return Ok((serde_json::to_string_pretty(&root)? + "\n", removed));
    }
    render(root, hooks).map(|text| (text, removed))
}

fn remove_from_entry<F>(
    entry: Entry,
    predicate: &mut F,
    removed: &mut Vec<String>,
) -> Result<Option<(Entry, bool)>, serde_json::Error>
where
    F: FnMut(&str) -> bool,
{
    match entry {
        Entry::Ordered(value) => Ok(remove_from_ordered(value, predicate, removed)
            .map(|(value, changed)| (Entry::Ordered(value), changed))),
        Entry::Raw(raw) => {
            let value = serde_json::from_str(raw.get())?;
            Ok(match remove_from_ordered(value, predicate, removed) {
                Some((_, false)) => Some((Entry::Raw(raw), false)),
                Some((value, true)) => Some((Entry::Ordered(value), true)),
                None => None,
            })
        }
    }
}

fn remove_from_ordered<F>(
    entry: OrderedValue,
    predicate: &mut F,
    removed: &mut Vec<String>,
) -> Option<(OrderedValue, bool)>
where
    F: FnMut(&str) -> bool,
{
    let OrderedValue::Object(mut fields) = entry else {
        return Some((entry, false));
    };

    if let Some(command) = command_in_ordered(&fields).map(str::to_owned)
        && predicate(&command)
    {
        removed.push(command);
        return None;
    }

    let (changed, empty) = {
        let Some(OrderedValue::Array(hook_entries)) = fields.get_mut("hooks") else {
            return Some((OrderedValue::Object(fields), false));
        };

        let mut changed = false;
        let mut kept = Vec::with_capacity(hook_entries.len());
        for hook_entry in hook_entries.drain(..) {
            let matches = command_in_ordered_value(&hook_entry).is_some_and(|command| {
                if predicate(command) {
                    removed.push(command.to_owned());
                    true
                } else {
                    false
                }
            });
            if matches {
                changed = true;
            } else {
                kept.push(hook_entry);
            }
        }
        *hook_entries = kept;
        (changed, hook_entries.is_empty())
    };

    if !changed {
        return Some((OrderedValue::Object(fields), false));
    }
    if empty {
        return None;
    }

    Some((OrderedValue::Object(fields), true))
}

fn command_in_ordered(fields: &IndexMap<String, OrderedValue>) -> Option<&str> {
    match fields.get("command")? {
        OrderedValue::String(command) => Some(command),
        _ => None,
    }
}

fn command_in_ordered_value(value: &OrderedValue) -> Option<&str> {
    match value {
        OrderedValue::Object(fields) => command_in_ordered(fields),
        _ => None,
    }
}

fn raw_entries_pretty(
    value: &RawEntries,
    continuation_indent: usize,
) -> Result<Box<RawValue>, serde_json::Error> {
    if value.is_empty() {
        return RawValue::from_string("[]".to_owned());
    }
    let entry_indent = " ".repeat(continuation_indent + 2);
    let mut items = Vec::with_capacity(value.len());
    for entry in value {
        let text = match entry {
            Entry::Raw(raw) => raw.get().to_owned(),
            Entry::Ordered(ordered) => {
                serde_json::to_string_pretty(ordered)?.replace('\n', &format!("\n{entry_indent}"))
            }
        };
        items.push(format!("{entry_indent}{text}"));
    }
    let closing = " ".repeat(continuation_indent);
    RawValue::from_string(format!("[\n{}\n{closing}]", items.join(",\n")))
}

struct OrderedRoot<'a> {
    fields: &'a Object,
    hooks: &'a Object,
}

impl Serialize for OrderedRoot<'_> {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        let has_hooks = self.fields.contains_key("hooks");
        let mut map =
            serializer.serialize_map(Some(self.fields.len() + usize::from(!has_hooks)))?;
        for (key, value) in self.fields {
            if key == "hooks" {
                map.serialize_entry(key, self.hooks)?;
            } else {
                map.serialize_entry(key, value)?;
            }
        }
        if !has_hooks {
            map.serialize_entry("hooks", self.hooks)?;
        }
        map.end()
    }
}

fn render(root: Object, hooks: Object) -> Result<String, serde_json::Error> {
    Ok(serde_json::to_string_pretty(&OrderedRoot {
        fields: &root,
        hooks: &hooks,
    })? + "\n")
}

#[cfg(test)]
mod tests {
    use super::{
        RemoveOptions, append_entry, remove_matching_commands,
        remove_matching_commands_with_options, replace_owned_entries,
        replace_owned_entries_from_json,
    };
    use serde_json::json;

    #[test]
    fn append_preserves_top_level_event_and_foreign_entry_order() {
        let input = r#"{"z_last": { "nested" : {"b": 2, "a": 1} }, "hooks": {"Stop" : [ { "z": 0, "command" : "echo keep", "a": 1 } ], "PreToolUse": [{"hooks":[{"command":"foreign"}]}]}, "a_first": [1, 2]}"#;

        let output = append_entry(
            input,
            "SessionStart",
            &json!({"type": "command", "command": "varde hook"}),
        )
        .unwrap();

        let z_last = output.find("\"z_last\"").unwrap();
        let hooks = output.find("\"hooks\"").unwrap();
        let a_first = output.find("\"a_first\"").unwrap();
        assert!(z_last < hooks && hooks < a_first);
        let stop = output.find("\"Stop\"").unwrap();
        let pre_tool_use = output.find("\"PreToolUse\"").unwrap();
        let session_start = output.find("\"SessionStart\"").unwrap();
        assert!(stop < pre_tool_use && pre_tool_use < session_start);
        assert!(output.contains(r#"{ "nested" : {"b": 2, "a": 1} }"#));
        assert!(output.contains(r#"{ "z": 0, "command" : "echo keep", "a": 1 }"#));
        assert!(output.ends_with('\n'));
    }

    #[test]
    fn append_creates_an_event_in_an_empty_hooks_object() {
        let output = append_entry(
            r#"{"z_last":1,"hooks":{},"a_first":2}"#,
            "SessionStart",
            &json!({"command": "owned"}),
        )
        .unwrap();

        assert!(output.find("\"z_last\"").unwrap() < output.find("\"hooks\"").unwrap());
        assert!(output.find("\"hooks\"").unwrap() < output.find("\"a_first\"").unwrap());
        assert!(output.contains("\"SessionStart\""));
    }

    #[test]
    fn remove_matching_commands_keeps_foreign_hooks_and_entry_key_order() {
        let input = r#"{"hooks":{"SessionStart":[{"metadata":{"y":1,"x":2},"hooks":[{"type":"command","command":"owned"},{"type":"command","command":"foreign"}],"tail":3}],"Stop":[{"z":1,"a":2}]}}"#;

        let (output, removed) =
            remove_matching_commands(input, "SessionStart", |command| command == "owned").unwrap();

        assert_eq!(removed, ["owned"]);
        let metadata = output.find("\"metadata\"").unwrap();
        let hooks = metadata + output[metadata..].find("\"hooks\"").unwrap();
        let tail = metadata + output[metadata..].find("\"tail\"").unwrap();
        assert!(metadata < hooks && hooks < tail);
        assert!(output.find("\"y\": 1").unwrap() < output.find("\"x\": 2").unwrap());
        assert!(output.contains("\"command\": \"foreign\""));
        assert!(output.contains("\"Stop\""));
    }

    #[test]
    fn removing_last_event_can_prune_empty_hooks_without_changing_default() {
        let input = r#"{"z-last":1,"hooks":{"SessionStart":[{"command":"owned"}]} ,"a-first":2}"#;

        let (default_output, default_removed) =
            remove_matching_commands(input, "SessionStart", |command| command == "owned").unwrap();
        assert_eq!(default_removed, ["owned"]);
        let default_doc: serde_json::Value = serde_json::from_str(&default_output).unwrap();
        assert!(default_doc["hooks"].as_object().unwrap().is_empty());

        let (pruned_output, pruned_removed) = remove_matching_commands_with_options(
            input,
            "SessionStart",
            |command| command == "owned",
            RemoveOptions {
                prune_empty_hooks: true,
            },
        )
        .unwrap();

        assert_eq!(pruned_removed, ["owned"]);
        assert_eq!(pruned_output, "{\n  \"z-last\": 1,\n  \"a-first\": 2\n}\n");
    }

    #[test]
    fn replace_owned_entries_replaces_only_matching_commands() {
        let input = r#"{"hooks":{"SessionStart":[{"hooks":[{"command":"old"},{"command":"foreign"}]}],"Stop":[{"z":1,"a":2}]}}"#;

        let (output, removed) = replace_owned_entries(
            input,
            "SessionStart",
            |command| command == "old",
            &[json!({"command": "new"})],
        )
        .unwrap();

        assert_eq!(removed, ["old"]);
        assert!(output.contains("\"new\""));
        assert!(output.contains("\"foreign\""));
        assert!(output.find("\"SessionStart\"").unwrap() < output.find("\"Stop\"").unwrap());
    }

    #[test]
    fn editing_an_event_keeps_untouched_compact_entries_byte_for_byte() {
        let foreign = r#"{ "z":0,"command" : "foreign","a":[1,  2] }"#;
        let input = format!(r#"{{"hooks":{{"Stop":[{foreign},{{"command":"owned"}}]}}}}"#);

        let (output, removed) = replace_owned_entries(
            &input,
            "Stop",
            |command| command == "owned",
            &[json!({"command": "new"})],
        )
        .unwrap();

        assert_eq!(removed, ["owned"]);
        assert!(output.contains(foreign), "{output}");
        assert!(output.contains("\"new\""));
        assert!(!output.contains("owned"));
    }

    #[test]
    fn replacement_entry_uses_nested_indentation_and_field_order() {
        let entry = serde_json::value::RawValue::from_string(
            r#"{"hooks":[{"type":"command","command":"owned","timeout":20}]}"#.to_owned(),
        )
        .unwrap();
        let (output, removed) =
            replace_owned_entries(r#"{"hooks":{}}"#, "SessionStart", |_| false, &[entry]).unwrap();
        assert!(removed.is_empty());

        assert_eq!(
            output,
            "{\n  \"hooks\": {\n    \"SessionStart\": [\n      {\n        \"hooks\": [\n          {\n            \"type\": \"command\",\n            \"command\": \"owned\",\n            \"timeout\": 20\n          }\n        ]\n      }\n    ]\n  }\n}\n"
        );
    }

    #[test]
    fn replacing_an_owned_entry_keeps_nested_user_indentation_stable() {
        let input = r#"{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "foreign"
          }
        ]
      },
      {
        "type": "command",
        "command": "owned"
      }
    ]
  }
}
"#;
        let replacement = serde_json::value::RawValue::from_string(
            r#"{"type":"command","command":"owned"}"#.to_owned(),
        )
        .unwrap();

        let (first, _) = replace_owned_entries(
            input,
            "SessionStart",
            |command| command == "owned",
            &[replacement.clone()],
        )
        .unwrap();
        let (second, _) = replace_owned_entries(
            &first,
            "SessionStart",
            |command| command == "owned",
            &[replacement],
        )
        .unwrap();

        assert_eq!(second, first);
    }

    #[test]
    fn replacement_document_preserves_asset_field_order_and_indentation() {
        let input = r#"{"hooks":{}}"#;
        let replacements = r#"{"hooks":{"PostToolUse":[{"type":"command","command":"owned"}]}}"#;
        let (output, removed) = replace_owned_entries_from_json(
            input,
            "PostToolUse",
            |_| false,
            replacements,
            "PostToolUse",
        )
        .unwrap();

        assert!(removed.is_empty());
        assert!(
            output.contains(
                "    \"PostToolUse\": [\n      {\n        \"type\": \"command\",\n        \"command\": \"owned\"\n      }\n    ]"
            ),
            "{output}"
        );
    }
}
