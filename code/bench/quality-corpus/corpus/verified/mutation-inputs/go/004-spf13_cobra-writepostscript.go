func writePostscript(buf io.StringWriter, name string) {
	name = strings.ReplaceAll(name, ":", "__")
	WriteStringAndCheck(buf, fmt.Sprintf("__start_%s()\n", name))
	WriteStringAndCheck(buf, fmt.Sprintf(`{
    local cur prev words cword split
    declare -A flaghash 2>/dev/null || :
    declare -A aliashash 2>/dev/null || :
    if declare -F _init_completion >/dev/null 2>&1; then
        _init_completion -s || return
    else
        __%[1]s_init_completion -n "=" || return
    fi

    local c=0
    local flag_parsing_disabled=
    local flags=()
    local two_word_flags=()
    local local_nonpersistent_flags=()
    local flags_with_completion=()
    local flags_completion=()
    local commands=("%[1]s")
    local command_aliases=()
    local must_have_one_flag=()
    local must_have_one_noun=()
    local has_completion_function=""
    local last_command=""
    local nouns=()
    local noun_aliases=()

    __%[1]s_handle_word
}

`, name))
	WriteStringAndCheck(buf, fmt.Sprintf(`if [[ $(type -t compopt) = "builtin" ]]; then
    complete -o default -F __start_%s %s
else
    complete -o default -o nospace -F __start_%s %s
fi

`, name, name, name, name))
	WriteStringAndCheck(buf, "# ex: ts=4 sw=4 et filetype=sh\n")
}
