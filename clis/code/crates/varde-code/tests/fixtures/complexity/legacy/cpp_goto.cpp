int choose(bool value) {
    if (value) goto done;
done:
    return value ? 1 : 0;
}
