// Table layout chosen by hand; keep in sync with the parser.
int parser_table[4] = { 1, 2, 3, 4 };

int lookup(int key) {
    return parser_table[key % 4];
}
