// SPDX-License-Identifier: MIT

fn gen_fish_inner(
    root_command: &str,
    parent_commands: &[&str],
    cmd: &Command,
    buffer: &mut String,
) {
    debug!("gen_fish_inner");
    // example :
    //
    // complete
    //      -c {command}
    //      -d "{description}"
    //      -s {short}
    //      -l {long}
    //      -a "{possible_arguments}"
    //      -r # if require parameter
    //      -f # don't use file completion
    //      -n "__fish_use_subcommand"               # complete for command "myprog"
    //      -n "__fish_seen_subcommand_from subcmd1" # complete for command "myprog subcmd1"

    let mut basic_template = format!("complete -c {root_command}");

    if parent_commands.is_empty() {
        if cmd.has_subcommands() {
            basic_template.push_str(" -n \"__fish_use_subcommand\"");
        }
    } else {
        basic_template.push_str(
            format!(
                " -n \"{}\"",
                parent_commands
                    .iter()
                    .map(|command| format!("__fish_seen_subcommand_from {command}"))
                    .chain(
                        cmd.get_subcommands()
                            .flat_map(Command::get_name_and_visible_aliases)
                            .map(|name| format!("not __fish_seen_subcommand_from {name}"))
                    )
                    .collect::<Vec<_>>()
                    .join("; and ")
            )
            .as_str(),
        );
    }

    debug!("gen_fish_inner: parent_commands={parent_commands:?}");

    for option in cmd.get_opts() {
        let mut template = basic_template.clone();

        if let Some(shorts) = option.get_short_and_visible_aliases() {
            for short in shorts {
                template.push_str(format!(" -s {short}").as_str());
            }
        }

        if let Some(longs) = option.get_long_and_visible_aliases() {
            for long in longs {
                template.push_str(format!(" -l {}", escape_string(long, false)).as_str());
            }
        }

        if let Some(data) = option.get_help() {
            template.push_str(&format!(" -d '{}'", escape_help(data)));
        }

        template.push_str(value_completion(option).as_str());

        buffer.push_str(template.as_str());
        buffer.push('\n');
    }

    for flag in utils::flags(cmd) {
        let mut template = basic_template.clone();

        if let Some(shorts) = flag.get_short_and_visible_aliases() {
            for short in shorts {
                template.push_str(format!(" -s {short}").as_str());
            }
        }

        if let Some(longs) = flag.get_long_and_visible_aliases() {
            for long in longs {
                template.push_str(format!(" -l {}", escape_string(long, false)).as_str());
            }
        }

        if let Some(data) = flag.get_help() {
            template.push_str(&format!(" -d '{}'", escape_help(data)));
        }

        buffer.push_str(template.as_str());
        buffer.push('\n');
    }

    for subcommand in cmd.get_subcommands() {
        for subcommand_name in subcommand.get_name_and_visible_aliases() {
            let mut template = basic_template.clone();

            template.push_str(" -f");
            template.push_str(format!(" -a \"{}\"", subcommand_name).as_str());

            if let Some(data) = subcommand.get_about() {
                template.push_str(format!(" -d '{}'", escape_help(data)).as_str());
            }

            buffer.push_str(template.as_str());
            buffer.push('\n');
        }
    }

    // generate options of subcommands
    for subcommand in cmd.get_subcommands() {
        for subcommand_name in subcommand.get_name_and_visible_aliases() {
            let mut parent_commands: Vec<_> = parent_commands.into();
            parent_commands.push(subcommand_name);
            gen_fish_inner(root_command, &parent_commands, subcommand, buffer);
        }
    }
}